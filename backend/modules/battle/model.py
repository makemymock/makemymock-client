"""Mongo document factories for the battle module."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from bson import ObjectId


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# Invite codes use an unambiguous alphabet — no 0/O/1/I/L — so a friend
# typing the code by hand on a phone doesn't fat-finger lookalikes. 6
# chars × 32-char alphabet = ~1 billion combinations, plenty for the
# short-lived invites we're issuing.
_INVITE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
INVITE_CODE_LENGTH = 6
INVITE_TTL_MINUTES = 10


def make_invite_code() -> str:
    """Generate a fresh invite code. Caller is responsible for retrying
    on the (extremely unlikely) collision against the unique index."""
    return "".join(secrets.choice(_INVITE_ALPHABET) for _ in range(INVITE_CODE_LENGTH))


def new_battle_invite_doc(
    *,
    code: str,
    inviter_user_id: ObjectId,
    inviter_username: str,
) -> dict:
    """One pending invite. Status transitions: pending → accepted | cancelled
    | expired. `expires_at` is also the TTL key, so Mongo evicts old docs
    automatically — no cron job needed."""
    now = now_utc()
    return {
        "code": code,
        "inviter_user_id": inviter_user_id,
        "inviter_username": inviter_username,
        "invitee_user_id": None,
        "invitee_username": None,
        "status": "pending",
        "battle_id": None,
        "created_at": now,
        "expires_at": now + timedelta(minutes=INVITE_TTL_MINUTES),
        "accepted_at": None,
    }


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
