"""Document factories for POTD Mongo collections."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId

from modules.potd.constants import STATUS_IN_PROGRESS


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_potd_assignment_doc(
    *,
    user_id: ObjectId,
    date_ist: str,
    question_id: ObjectId,
    topic_id: int,
    question_type: str,
    difficulty: str,
    max_attempts: Optional[int],
) -> dict[str, Any]:
    """The question picked for one user on one IST calendar day.

    `max_attempts` is set only for `single_correct`; other types stay unlimited
    and store None. The cap travels on the assignment (not the state) so the
    front-end can show "Attempt 1 / 3" before any submit happens.
    """
    return {
        "user_id": user_id,
        "date_ist": date_ist,
        "question_id": question_id,
        "topic_id": int(topic_id),
        "question_type": question_type,
        "difficulty": difficulty,
        "max_attempts": max_attempts,
        "assigned_at": now_utc(),
    }


def new_potd_user_state_doc(
    *,
    user_id: ObjectId,
    date_ist: str,
    question_id: ObjectId,
) -> dict[str, Any]:
    """A fresh per-day engagement row for a user.

    `status` walks through in_progress → (solved | exhausted | viewed) as
    the user attempts the question. The streak query reads this collection
    directly — it does not need to join with assignments because the streak
    cares only about "did the user solve POTD on day X?".
    """
    now = now_utc()
    return {
        "user_id": user_id,
        "date_ist": date_ist,
        "question_id": question_id,
        "status": STATUS_IN_PROGRESS,
        "attempt_count": 0,
        "first_correct_at": None,
        "last_attempt_at": None,
        "created_at": now,
        "updated_at": now,
    }
