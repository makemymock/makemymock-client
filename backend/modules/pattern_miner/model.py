"""Mongo document factories + the doc → domain mapper.

Following the backend convention, every pattern / assignment document is built
here so timestamps, the uuid pattern_id, and the prompt-version stamp stay
consistent across the repository's insert and upsert paths.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from modules.pattern_miner.constants import PROMPT_VERSION
from modules.pattern_miner.domain import Pattern, PatternDraft, PatternSignature


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_pattern_doc(
    *,
    chapter: str,
    canonical_question_id: str,
    draft: PatternDraft,
) -> dict[str, Any]:
    """A fresh `patterns` row, seeded by the question that proposed it.
    member_count starts at 1 (the seeding question is its first member)."""
    now = now_utc()
    return {
        "pattern_id": str(uuid.uuid4()),
        "chapter": chapter,
        "slug": draft.slug,
        "name": draft.name,
        "description": draft.description,
        "signature": draft.signature.model_dump(),
        "canonical_question_id": canonical_question_id,
        "member_count": 1,
        "prompt_version": PROMPT_VERSION,
        "created_at": now,
        "updated_at": now,
    }


def new_assignment_doc(
    *,
    question_id: str,
    pattern_id: str,
    confidence: float,
    rationale: str,
    decided_by: str,
) -> dict[str, Any]:
    """The `$set` payload for a `pattern_assignments` upsert. Keyed externally
    on question_id so a re-run overwrites the same row."""
    return {
        "question_id": question_id,
        "pattern_id": pattern_id,
        "confidence": float(confidence),
        "rationale": rationale,
        "prompt_version": PROMPT_VERSION,
        "decided_by": decided_by,
        "created_at": now_utc(),
    }


def doc_to_pattern(d: dict) -> Pattern:
    sig = d.get("signature") or {}
    return Pattern(
        pattern_id=d["pattern_id"],
        chapter=d["chapter"],
        slug=d["slug"],
        name=d["name"],
        description=d["description"],
        signature=PatternSignature(
            trigger=sig.get("trigger", ""),
            technique=sig.get("technique", ""),
            why_it_works=sig.get("why_it_works", ""),
        ),
        canonical_question_id=d.get("canonical_question_id", ""),
        member_count=int(d.get("member_count", 0)),
        prompt_version=d.get("prompt_version", "v1"),
        created_at=d["created_at"],
        updated_at=d.get("updated_at"),
    )
