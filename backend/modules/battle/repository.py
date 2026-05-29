"""Mongo I/O for the battle module.

Reads random questions from the shared `questions` catalog and persists
completed battles to `battles`. Never touches mock-test collections.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from modules.battle.constants import (
    BATTLES_COLLECTION,
    QUESTIONS_COLLECTION,
)

logger = logging.getLogger(__name__)

INVITES_COLLECTION = "battle_invites"


class BattleRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.battles = db[BATTLES_COLLECTION]
        self.questions = db[QUESTIONS_COLLECTION]
        self.invites = db[INVITES_COLLECTION]

    # ------------------------------------------------------------------
    # Question sourcing
    # ------------------------------------------------------------------

    async def sample_random_questions(self, count: int) -> list[dict]:
        """Sample `count` random single_correct questions from the catalog.

        Filters out anything without a usable correct answer so we don't
        ship a malformed question into the arena.
        """
        pipeline = [
            {"$match": {
                "questionType": "single_correct",
                "$or": [
                    {"correctOption": {"$exists": True, "$ne": None}},
                    {"correctOptions.0": {"$exists": True}},
                ],
            }},
            {"$sample": {"size": count}},
        ]
        docs = await self.questions.aggregate(pipeline).to_list(length=count)
        # Filter again in Python — `$sample` doesn't re-run match if the
        # collection is small enough to skip the lookup.
        return [d for d in docs if _has_correct_answer(d)]

    # ------------------------------------------------------------------
    # Battle persistence
    # ------------------------------------------------------------------

    async def insert_battle(self, doc: dict) -> None:
        await self.battles.insert_one(doc)

    async def list_user_battles(
        self, user_oid: ObjectId, *, limit: int = 50,
    ) -> list[dict]:
        cursor = self.battles.find(
            {"$or": [
                {"player_a.user_id": user_oid},
                {"player_b.user_id": user_oid},
            ]},
        ).sort("completed_at", -1).limit(limit)
        return [d async for d in cursor]

    async def get_battle(
        self, battle_id: str, user_oid: ObjectId,
    ) -> Optional[dict]:
        return await self.battles.find_one({
            "_id": battle_id,
            "$or": [
                {"player_a.user_id": user_oid},
                {"player_b.user_id": user_oid},
            ],
        })


def _has_correct_answer(doc: dict) -> bool:
    if doc.get("correctOption"):
        return True
    co = doc.get("correctOptions") or []
    return len(co) > 0


# ---------------------------------------------------------------------------
# Battle invite I/O — separate methods on the same repository class.
# ---------------------------------------------------------------------------


class BattleInviteRepository:
    """Mongo I/O for the battle_invites collection. Kept as its own class
    so the invite service doesn't pull in question-sourcing concerns."""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.col = db[INVITES_COLLECTION]

    async def insert(self, doc: dict) -> dict:
        await self.col.insert_one(doc)
        return doc

    async def get_by_code(self, code: str) -> Optional[dict]:
        return await self.col.find_one({"code": code})

    async def mark_accepted(
        self,
        code: str,
        *,
        invitee_oid: ObjectId,
        invitee_username: str,
    ) -> Optional[dict]:
        """Atomic CAS: only flip pending → accepted, and refuse if the
        invitee is the same person as the inviter (can't invite yourself).
        Returns the post-update doc, or None when the CAS failed (already
        accepted, expired, cancelled, or self-invite)."""
        now = datetime.now(timezone.utc)
        return await self.col.find_one_and_update(
            {
                "code": code,
                "status": "pending",
                "expires_at": {"$gt": now},
                "inviter_user_id": {"$ne": invitee_oid},
            },
            {
                "$set": {
                    "status": "accepted",
                    "invitee_user_id": invitee_oid,
                    "invitee_username": invitee_username,
                    "accepted_at": now,
                },
            },
            return_document=True,  # ReturnDocument.AFTER
        )

    async def mark_cancelled(
        self,
        code: str,
        inviter_oid: ObjectId,
    ) -> Optional[dict]:
        """Cancel only if the requesting user is the inviter and the
        invite is still pending."""
        return await self.col.find_one_and_update(
            {
                "code": code,
                "inviter_user_id": inviter_oid,
                "status": "pending",
            },
            {"$set": {"status": "cancelled"}},
            return_document=True,
        )

    async def attach_battle_id(self, code: str, battle_id: str) -> None:
        """Once the WS pair-up creates a Battle, stamp its id on the invite
        for audit and so the inviter's polling loops can fetch it."""
        await self.col.update_one(
            {"code": code},
            {"$set": {"battle_id": battle_id}},
        )
