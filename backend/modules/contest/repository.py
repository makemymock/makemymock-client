"""Mongo I/O for the student-facing contest module.

Read-mostly on `contests` (admin owns writes). This module owns writes
to `contest_participations` and `contest_responses`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

from modules.contest.constants import (
    CONTESTS_COLLECTION,
    PARTICIPATIONS_COLLECTION,
    QUESTIONS_COLLECTION,
    RESPONSES_COLLECTION,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ContestRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.col = db[CONTESTS_COLLECTION]
        self.part_col = db[PARTICIPATIONS_COLLECTION]
        self.resp_col = db[RESPONSES_COLLECTION]
        # `questions` lives in the same logical DB as the rest of the
        # Client backend writes — same convention as mock_test/.
        self.q_col = db[QUESTIONS_COLLECTION]

    # --------------------- contests (read-only) ---------------------

    async def list_visible(self) -> list[dict[str, Any]]:
        cursor = self.col.find({}).sort("start_time", DESCENDING)
        return [d async for d in cursor]

    async def get(self, contest_id: str) -> Optional[dict[str, Any]]:
        try:
            oid = ObjectId(contest_id)
        except Exception:
            return None
        return await self.col.find_one({"_id": oid})

    async def fetch_questions_in_order(self, ids: list[Any]) -> list[dict[str, Any]]:
        oids: list[ObjectId] = []
        order: dict[str, int] = {}
        for i, raw in enumerate(ids):
            try:
                oid = raw if isinstance(raw, ObjectId) else ObjectId(raw)
            except Exception:
                continue
            oids.append(oid)
            order[str(oid)] = i
        if not oids:
            return []
        docs = [d async for d in self.q_col.find({"_id": {"$in": oids}})]
        docs.sort(key=lambda d: order.get(str(d.get("_id")), 1 << 30))
        return docs

    # --------------------- participations ---------------------

    async def get_participation(
        self, contest_id: ObjectId, user_id: ObjectId,
    ) -> Optional[dict[str, Any]]:
        return await self.part_col.find_one(
            {"contest_id": contest_id, "user_id": user_id},
        )

    async def upsert_lobby_entry(
        self, contest_id: ObjectId, user_id: ObjectId, username: str,
    ) -> dict[str, Any]:
        """Idempotent: if the row already exists we just return it."""
        now = _utcnow()
        await self.part_col.update_one(
            {"contest_id": contest_id, "user_id": user_id},
            {
                "$setOnInsert": {
                    "contest_id": contest_id,
                    "user_id": user_id,
                    "username": username,
                    "entered_at": now,
                    "status": "entered",
                },
            },
            upsert=True,
        )
        doc = await self.part_col.find_one(
            {"contest_id": contest_id, "user_id": user_id},
        )
        assert doc is not None  # we just upserted it
        return doc

    async def mark_started(
        self, contest_id: ObjectId, user_id: ObjectId,
    ) -> dict[str, Any]:
        now = _utcnow()
        await self.part_col.update_one(
            {"contest_id": contest_id, "user_id": user_id},
            {
                "$setOnInsert": {
                    "contest_id": contest_id,
                    "user_id": user_id,
                    "entered_at": now,
                },
                "$set": {
                    "started_at": now,
                    "status": "in_progress",
                },
            },
            upsert=True,
        )
        doc = await self.part_col.find_one(
            {"contest_id": contest_id, "user_id": user_id},
        )
        assert doc is not None
        return doc

    async def mark_submitted(
        self,
        contest_id: ObjectId,
        user_id: ObjectId,
        *,
        score: float,
        correct_count: int,
        wrong_count: int,
        unattempted_count: int,
        time_taken_seconds: int,
    ) -> None:
        await self.part_col.update_one(
            {"contest_id": contest_id, "user_id": user_id},
            {
                "$set": {
                    "submitted_at": _utcnow(),
                    "status": "submitted",
                    "score": score,
                    "correct_count": correct_count,
                    "wrong_count": wrong_count,
                    "unattempted_count": unattempted_count,
                    "time_taken_seconds": time_taken_seconds,
                },
            },
        )

    async def list_participations_for_user(
        self, user_id: ObjectId,
    ) -> list[dict[str, Any]]:
        cursor = self.part_col.find({"user_id": user_id})
        return [d async for d in cursor]

    # --------------------- responses ---------------------

    async def replace_responses(
        self,
        contest_id: ObjectId,
        user_id: ObjectId,
        rows: list[dict[str, Any]],
    ) -> None:
        """Idempotent: wipe + insert. Submissions only happen once per
        (contest, user), and the service enforces that — this is just
        defense in depth so a retry can't double-count."""
        await self.resp_col.delete_many(
            {"contest_id": contest_id, "user_id": user_id},
        )
        if rows:
            await self.resp_col.insert_many(rows)

    async def list_responses(
        self, contest_id: ObjectId, user_id: ObjectId,
    ) -> list[dict[str, Any]]:
        cursor = self.resp_col.find(
            {"contest_id": contest_id, "user_id": user_id}
        ).sort("display_order", ASCENDING)
        return [d async for d in cursor]

    # --------------------- leaderboard ---------------------

    async def leaderboard(
        self, contest_id: ObjectId, *, limit: int,
    ) -> list[dict[str, Any]]:
        cursor = self.part_col.find(
            {"contest_id": contest_id, "submitted_at": {"$ne": None}},
        ).sort([
            ("score", DESCENDING),
            ("time_taken_seconds", ASCENDING),
        ]).limit(limit)
        return [d async for d in cursor]

    async def count_submitted(self, contest_id: ObjectId) -> int:
        return await self.part_col.count_documents(
            {"contest_id": contest_id, "submitted_at": {"$ne": None}},
        )
