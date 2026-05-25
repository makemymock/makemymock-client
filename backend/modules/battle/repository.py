"""Mongo I/O for the battle module.

Reads random questions from the shared `questions` catalog and persists
completed battles to `battles`. Never touches mock-test collections.
"""

from __future__ import annotations

import logging
from typing import Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from modules.battle.constants import (
    BATTLES_COLLECTION,
    QUESTIONS_COLLECTION,
)

logger = logging.getLogger(__name__)


class BattleRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.battles = db[BATTLES_COLLECTION]
        self.questions = db[QUESTIONS_COLLECTION]

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
