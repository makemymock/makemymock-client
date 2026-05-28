"""Document factories for mock-test Mongo collections.

Centralizes the shape of every document the module persists, so service and
repository code stays consistent.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_session_doc(
    *,
    session_id: int,
    user_id: ObjectId,
    total_questions: int,
    extra_questions: int,
    total_seconds: int,
    topic_ids: list[int],
    status: str = "pending",
) -> dict[str, Any]:
    now = now_utc()
    return {
        "_id": session_id,
        "user_id": user_id,
        "total_questions": total_questions,
        "extra_questions": extra_questions,
        "total_seconds": total_seconds,
        "topic_ids": topic_ids,
        "status": status,
        "created_at": now,
        "completed_at": None,
        "score": None,
        "correct": None,
        "incorrect": None,
        "partial": None,
    }


def new_topic_allocation_doc(
    *,
    session_id: int,
    topic_id: int,
    question_count: int,
    priority_score: float,
    decay_factor: float,
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "topic_id": topic_id,
        "question_count": question_count,
        "priority_score": float(priority_score),
        "decay_factor": float(decay_factor),
        "created_at": now_utc(),
    }


def new_response_doc(
    *,
    session_id: int,
    question_id: int,
    topic_id: int,
    is_extra: bool,
    display_order: int,
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "question_id": question_id,
        "topic_id": topic_id,
        "is_extra": bool(is_extra),
        "display_order": display_order,
        "user_answer": None,
        "is_correct": None,
        "correctness": None,
        "answered_at": None,
    }


def new_practice_view_doc(
    *,
    user_id: ObjectId,
    obj_id: str,
) -> dict[str, Any]:
    """Marker that a user revealed a question's solution in Browse.

    Lives in `practice_solution_views` (unique on user_id + obj_id), kept
    out of `user_topic_attempts` so viewing never feeds the recommender.
    """
    return {
        "user_id": user_id,
        "obj_id": obj_id,
        "viewed_at": now_utc(),
    }


def new_notebook_entry_doc(
    *,
    user_id: ObjectId,
    obj_id: str,
) -> dict[str, Any]:
    """A question the user marked to revise later.

    Lives in `notebook_entries` (unique on user_id + obj_id), so the same
    question can never be added twice.
    """
    return {
        "user_id": user_id,
        "obj_id": obj_id,
        "added_at": now_utc(),
    }


def new_attempt_doc(
    *,
    user_id: ObjectId,
    question_id: int,
    topic_id: int,
    is_correct: bool,
    correctness: Optional[float],
    difficulty: str,
    score_contribution: int,
    attempted_at: datetime,
    session_id: int,
) -> dict[str, Any]:
    """Full "feeding" attempt row.

    The `e_*` fields mirror the user-visible fields at feed-time so the
    recommender only ever reads honest signal: subsequent non-feeding
    cooldown attempts overwrite the user-visible fields (so badges show
    the latest result) but leave the `e_*` fields untouched.
    """
    return {
        "user_id": user_id,
        "question_id": question_id,
        "topic_id": topic_id,
        # User-visible "latest attempt" fields — overwritten by every attempt.
        "is_correct": bool(is_correct),
        "correctness": correctness,
        "difficulty": difficulty,
        "score_contribution": int(score_contribution),
        "attempted_at": attempted_at,
        "session_id": session_id,
        # Engine-only mirror — updated only on feeding attempts. Engine
        # priority computation reads these so cooldown attempts can't
        # contaminate recommender signal.
        "e_is_correct": bool(is_correct),
        "e_correctness": correctness,
        "e_difficulty": difficulty,
        "e_score_contribution": int(score_contribution),
        "e_attempted_at": attempted_at,
        "e_session_id": session_id,
        # Cooldown clock — bumped on any event (attempt or solution view).
        "last_event_at": attempted_at,
    }
