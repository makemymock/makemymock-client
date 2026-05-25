"""Mongo document factories for the battle module."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_battle_doc(
    *,
    battle_id: str,
    player_a_user_id: ObjectId,
    player_a_username: str,
    player_b_user_id: ObjectId,
    player_b_username: str,
    questions: list[dict],
    rounds: list[dict],
    player_a_score: int,
    player_b_score: int,
    player_a_correct: int,
    player_b_correct: int,
    winner_user_id: Optional[ObjectId],   # None on draw
    started_at: datetime,
    completed_at: datetime,
) -> dict:
    """Build the persisted battle doc.

    `questions` is the snapshot of question summaries used in this battle
    (stripped of answer keys is fine for replay), `rounds` contains the
    per-round outcomes for both players.
    """
    return {
        "_id": battle_id,
        "player_a": {
            "user_id": player_a_user_id,
            "username": player_a_username,
            "score": player_a_score,
            "correct_count": player_a_correct,
        },
        "player_b": {
            "user_id": player_b_user_id,
            "username": player_b_username,
            "score": player_b_score,
            "correct_count": player_b_correct,
        },
        "questions": questions,
        "rounds": rounds,
        "winner_user_id": winner_user_id,
        "questions_count": len(questions),
        "started_at": started_at,
        "completed_at": completed_at,
        "created_at": now_utc(),
    }


def make_battle_id() -> str:
    """uuid4 hex — short, opaque, easy to log/route on."""
    return uuid.uuid4().hex
