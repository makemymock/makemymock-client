"""In-memory repository wrappers for `classify_all --dry-run`.

Why these matter: if we naively no-op writes, every question sees an empty
`patterns` collection and every one of them proposes a new pattern — the
matching path never gets exercised. So the wrappers keep the catalog growing
IN MEMORY as the run proceeds:

  * reads delegate to the real repo on first touch per chapter (so any
    existing patterns are visible), then read from the in-memory cache;
  * writes are intercepted, stamped with a uuid, and stored in the cache;
  * the next question in the same chapter sees the just-created patterns
    via `list_for_chapter` and may match them.

That makes a dry-run actually representative of what production would do —
just without any side effects on Mongo.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pymongo.errors import DuplicateKeyError

from modules.pattern_miner.constants import PROMPT_VERSION
from modules.pattern_miner.domain import Pattern, PatternDraft
from modules.pattern_miner.repository import PatternRepository


class InMemoryPatternRepository:
    """Quacks like PatternRepository. Reads pass through on first touch per
    chapter so existing patterns (if any) are visible. Writes go to memory only."""

    def __init__(self, real: PatternRepository) -> None:
        self._real = real
        self._cache: dict[str, list[Pattern]] = {}
        self._by_slug: dict[tuple[str, str], Pattern] = {}
        self._loaded: set[str] = set()
        self.created: list[Pattern] = []
        self.member_count_bumps: list[str] = []

    async def _ensure_loaded(self, chapter: str) -> None:
        if chapter in self._loaded:
            return
        existing = await self._real.list_for_chapter(chapter)
        self._cache[chapter] = list(existing)
        for p in existing:
            self._by_slug[(chapter, p.slug)] = p
        self._loaded.add(chapter)

    async def list_for_chapter(self, chapter: str) -> list[Pattern]:
        await self._ensure_loaded(chapter)
        return list(self._cache[chapter])

    async def get_by_id(self, pattern_id: str) -> Optional[Pattern]:
        for chap_patterns in self._cache.values():
            for p in chap_patterns:
                if p.pattern_id == pattern_id:
                    return p
        return None

    async def get_by_slug(self, chapter: str, slug: str) -> Optional[Pattern]:
        await self._ensure_loaded(chapter)
        return self._by_slug.get((chapter, slug))

    async def create(
        self,
        *,
        chapter: str,
        canonical_question_id: str,
        draft: PatternDraft,
    ) -> Pattern:
        await self._ensure_loaded(chapter)
        if (chapter, draft.slug) in self._by_slug:
            raise DuplicateKeyError(
                f"(chapter, slug) duplicate: ({chapter}, {draft.slug})"
            )
        now = datetime.now(timezone.utc)
        pattern = Pattern(
            pattern_id=str(uuid.uuid4()),
            chapter=chapter,
            slug=draft.slug,
            name=draft.name,
            description=draft.description,
            signature=draft.signature,
            canonical_question_id=canonical_question_id,
            member_count=1,
            prompt_version=PROMPT_VERSION,
            created_at=now,
            updated_at=now,
        )
        self._cache.setdefault(chapter, []).append(pattern)
        self._by_slug[(chapter, pattern.slug)] = pattern
        self.created.append(pattern)
        return pattern

    async def increment_member_count(self, pattern_id: str) -> None:
        self.member_count_bumps.append(pattern_id)
        # Reflect the bump in the cached object too (Pattern is frozen, so swap
        # in a copy) — keeps member_count realistic for dedupe / display.
        for chap, plist in self._cache.items():
            for idx, p in enumerate(plist):
                if p.pattern_id == pattern_id:
                    updated = p.model_copy(update={"member_count": p.member_count + 1})
                    plist[idx] = updated
                    self._by_slug[(chap, p.slug)] = updated
                    return

    async def set_member_count(self, pattern_id: str, count: int) -> None:
        for chap, plist in self._cache.items():
            for idx, p in enumerate(plist):
                if p.pattern_id == pattern_id:
                    updated = p.model_copy(update={"member_count": int(count)})
                    plist[idx] = updated
                    self._by_slug[(chap, p.slug)] = updated
                    return

    async def delete(self, pattern_id: str) -> bool:
        removed = False
        for chap, plist in list(self._cache.items()):
            for p in list(plist):
                if p.pattern_id == pattern_id:
                    plist.remove(p)
                    self._by_slug.pop((chap, p.slug), None)
                    removed = True
        self.created = [p for p in self.created if p.pattern_id != pattern_id]
        return removed

    async def distinct_chapters(self) -> list[str]:
        return [c for c, plist in self._cache.items() if plist]

    def name_for(self, pattern_id: str) -> Optional[str]:
        """Synchronous name lookup for the verbose printer. Scans the in-memory
        caches (which hold both loaded-existing and just-created patterns)."""
        for chap_patterns in self._cache.values():
            for p in chap_patterns:
                if p.pattern_id == pattern_id:
                    return p.name
        for p in self.created:
            if p.pattern_id == pattern_id:
                return p.name
        return None


class InMemoryAssignmentRepository:
    def __init__(self) -> None:
        self.assignments: list[dict] = []

    async def upsert(
        self,
        *,
        question_id: str,
        pattern_id: str,
        confidence: float,
        rationale: str,
        decided_by: str,
    ) -> None:
        row = {
            "question_id": question_id,
            "pattern_id": pattern_id,
            "confidence": confidence,
            "rationale": rationale,
            "decided_by": decided_by,
        }
        # Replace-by-question_id so re-processing overwrites, mirroring the real
        # repo's unique index on question_id (no duplicate rows).
        for i, a in enumerate(self.assignments):
            if a["question_id"] == question_id:
                self.assignments[i] = row
                return
        self.assignments.append(row)

    async def count(self) -> int:
        return len(self.assignments)

    async def count_for_pattern(self, pattern_id: str) -> int:
        return sum(1 for a in self.assignments if a["pattern_id"] == pattern_id)

    async def repoint(self, *, from_pattern_id: str, to_pattern_id: str) -> int:
        n = 0
        for a in self.assignments:
            if a["pattern_id"] == from_pattern_id:
                a["pattern_id"] = to_pattern_id
                n += 1
        return n


class InMemoryCheckpointRepository:
    """Dry runs always start clean — list_processed_ids returns empty."""

    def __init__(self) -> None:
        self.processed: set[str] = set()

    async def mark_processed(self, *, question_id: str, run_id: str) -> None:
        self.processed.add(question_id)

    async def list_processed_ids(self) -> set[str]:
        return set()
