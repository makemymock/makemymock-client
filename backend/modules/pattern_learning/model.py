"""Mongo document factory for pattern-path progress."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Union


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_attempt_doc(
    *,
    user_id: str,
    chapter: str,
    pattern_id: str,
    question_id: str,
    user_answer: Union[str, list[str]],
    is_correct: bool,
) -> dict[str, Any]:
    """One row per (student, question). `user_id` is the stringified primary-DB
    ObjectId — progress lives on the PYQ cluster, so we store the id as a string
    rather than a cross-cluster ObjectId reference. Upserted on resubmit; the
    `$setOnInsert` of created_at is applied by the repository."""
    now = now_utc()
    return {
        "user_id": user_id,
        "chapter": chapter,
        "pattern_id": pattern_id,
        "question_id": question_id,
        "user_answer": user_answer,
        "is_correct": bool(is_correct),
        "updated_at": now,
    }
