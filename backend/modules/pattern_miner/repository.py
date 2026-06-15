"""All Motor I/O for the pattern miner's collections.

Four collaborators, one per collection:

    PatternRepository     — CRUD over `patterns`
    AssignmentRepository  — upserts + re-points over `pattern_assignments`
    QuestionRepository    — read-only stream over `jee_mains_pyqs`
    CheckpointRepository  — resumability bookkeeping

Every repository takes the shared Motor database (`get_database()` / DBDep);
none of them open their own client. Keep `PatternRepository.list_for_chapter`
fast — the chapter lock calls it inside its critical section.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from modules.pattern_miner.constants import (
    ASSIGNMENTS_COLLECTION,
    CHECKPOINT_COLLECTION,
    PATTERNS_COLLECTION,
    PYQ_COLLECTION,
)
from modules.pattern_miner.domain import Pattern, PatternDraft
from modules.pattern_miner.model import (
    doc_to_pattern,
    new_assignment_doc,
    new_pattern_doc,
)


class PatternRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._col = db[PATTERNS_COLLECTION]

    async def list_for_chapter(self, chapter: str) -> list[Pattern]:
        docs = self._col.find({"chapter": chapter}).sort("created_at", 1)
        return [doc_to_pattern(d) async for d in docs]

    async def get_by_id(self, pattern_id: str) -> Optional[Pattern]:
        d = await self._col.find_one({"pattern_id": pattern_id})
        return doc_to_pattern(d) if d else None

    async def get_by_slug(self, chapter: str, slug: str) -> Optional[Pattern]:
        d = await self._col.find_one({"chapter": chapter, "slug": slug})
        return doc_to_pattern(d) if d else None

    async def create(
        self,
        *,
        chapter: str,
        canonical_question_id: str,
        draft: PatternDraft,
    ) -> Pattern:
        """Insert a new pattern. Raises pymongo.errors.DuplicateKeyError on
        (chapter, slug) collisions — caller must catch and fall back to
        `get_by_slug` to join the existing pattern."""
        doc = new_pattern_doc(
            chapter=chapter,
            canonical_question_id=canonical_question_id,
            draft=draft,
        )
        await self._col.insert_one(doc)
        return doc_to_pattern(doc)

    async def increment_member_count(self, pattern_id: str) -> None:
        await self._col.update_one(
            {"pattern_id": pattern_id},
            {"$inc": {"member_count": 1}, "$set": {"updated_at": datetime.now(timezone.utc)}},
        )

    async def set_member_count(self, pattern_id: str, count: int) -> None:
        """Overwrite member_count with an authoritative value (used after a
        dedupe merge re-points assignments — derive from the assignment
        collection rather than trusting the running counter)."""
        await self._col.update_one(
            {"pattern_id": pattern_id},
            {"$set": {"member_count": int(count), "updated_at": datetime.now(timezone.utc)}},
        )

    async def delete(self, pattern_id: str) -> bool:
        """Delete a pattern (the loser of a dedupe merge). Returns True if a
        document was removed."""
        res = await self._col.delete_one({"pattern_id": pattern_id})
        return res.deleted_count > 0

    async def distinct_chapters(self) -> list[str]:
        """Chapters that currently have at least one pattern."""
        return await self._col.distinct("chapter")

    async def chapter_coverage(self) -> list[dict]:
        """Per-chapter rollup for the read API: how many patterns each chapter
        has, and how many question-memberships those patterns account for."""
        pipeline = [
            {
                "$group": {
                    "_id": "$chapter",
                    "pattern_count": {"$sum": 1},
                    "question_count": {"$sum": "$member_count"},
                }
            },
            {"$sort": {"_id": 1}},
        ]
        out: list[dict] = []
        async for row in self._col.aggregate(pipeline):
            out.append(
                {
                    "chapter": row["_id"],
                    "pattern_count": int(row.get("pattern_count", 0)),
                    "question_count": int(row.get("question_count", 0)),
                }
            )
        return out


class AssignmentRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._col = db[ASSIGNMENTS_COLLECTION]

    async def upsert(
        self,
        *,
        question_id: str,
        pattern_id: str,
        confidence: float,
        rationale: str,
        decided_by: str,
    ) -> None:
        await self._col.update_one(
            {"question_id": question_id},
            {
                "$set": new_assignment_doc(
                    question_id=question_id,
                    pattern_id=pattern_id,
                    confidence=confidence,
                    rationale=rationale,
                    decided_by=decided_by,
                )
            },
            upsert=True,
        )

    async def count(self) -> int:
        return await self._col.count_documents({})

    async def count_for_pattern(self, pattern_id: str) -> int:
        return await self._col.count_documents({"pattern_id": pattern_id})

    async def question_ids_for_pattern(self, pattern_id: str) -> list[str]:
        cursor = self._col.find(
            {"pattern_id": pattern_id}, {"question_id": 1, "_id": 0}
        )
        return [d["question_id"] async for d in cursor if d.get("question_id")]

    async def repoint(self, *, from_pattern_id: str, to_pattern_id: str) -> int:
        """Re-point every assignment from one pattern to another (used by the
        dedupe merge). Returns the number of assignments moved. Safe w.r.t. the
        unique index on question_id — only pattern_id changes."""
        res = await self._col.update_many(
            {"pattern_id": from_pattern_id},
            {
                "$set": {
                    "pattern_id": to_pattern_id,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        return res.modified_count


class QuestionRepository:
    """Reads from `jee_mains_pyqs`. The pipeline only ever reads this catalog."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._col = db[PYQ_COLLECTION]

    async def get_by_id(self, question_id: str) -> Optional[dict]:
        return await self._col.find_one({"question_id": question_id})

    async def count_by_chapter(self, chapter: str) -> int:
        return await self._col.count_documents({"chapter": chapter})

    async def iterate(
        self,
        *,
        chapter: Optional[str] = None,
        subject: Optional[str] = None,
        skip_question_ids: Optional[set[str]] = None,
        batch_size: int = 100,
    ) -> AsyncIterator[dict]:
        """Stream questions, optionally scoped to one chapter or subject.

        `skip_question_ids` is used by `classify_all` to skip questions the
        checkpoint says are already processed.
        """
        query: dict = {}
        if chapter:
            query["chapter"] = chapter
        if subject:
            query["subject"] = subject
        # Atlas shared tiers reject `no_cursor_timeout=True`; rely on the
        # default 10-minute idle timeout instead. For 100-question dry runs
        # this is never a problem; if the live job ever stalls a cursor near
        # the limit, switch to skip/limit pagination over question_id.
        cursor = self._col.find(query).batch_size(batch_size)
        try:
            async for doc in cursor:
                if skip_question_ids and doc.get("question_id") in skip_question_ids:
                    continue
                yield doc
        finally:
            await cursor.close()

    async def list_distinct_chapters(self) -> list[str]:
        raw = await self._col.distinct("chapter")
        return sorted(c for c in raw if isinstance(c, str) and c)


class CheckpointRepository:
    """Records which question_ids a run has processed so it's resumable."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._col = db[CHECKPOINT_COLLECTION]

    async def mark_processed(self, *, question_id: str, run_id: str) -> None:
        await self._col.update_one(
            {"question_id": question_id},
            {"$set": {"question_id": question_id, "run_id": run_id}},
            upsert=True,
        )

    async def list_processed_ids(self) -> set[str]:
        out: set[str] = set()
        async for d in self._col.find({}, {"question_id": 1, "_id": 0}):
            qid = d.get("question_id")
            if qid:
                out.add(qid)
        return out

    async def clear(self) -> int:
        result = await self._col.delete_many({})
        return result.deleted_count
