"""Mongo I/O for SolverX conversations + messages."""

from __future__ import annotations

from typing import Any, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from modules.solverx.constants import (
    CONVERSATIONS_COLLECTION,
    MESSAGES_COLLECTION,
)


class SolverXRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.conv = db[CONVERSATIONS_COLLECTION]
        self.msg = db[MESSAGES_COLLECTION]

    # ---- conversation ----

    async def create_conversation(self, doc: dict[str, Any]) -> ObjectId:
        result = await self.conv.insert_one(doc)
        return result.inserted_id

    async def get_conversation(
        self, conv_id: str | ObjectId, user_oid: ObjectId,
    ) -> Optional[dict]:
        oid = conv_id if isinstance(conv_id, ObjectId) else ObjectId(conv_id)
        return await self.conv.find_one({"_id": oid, "user_id": user_oid})

    async def touch_conversation(
        self, conv_id: ObjectId, *, last_preview: str, increment_messages: int = 1
    ) -> None:
        from datetime import datetime, timezone
        await self.conv.update_one(
            {"_id": conv_id},
            {
                "$set": {
                    "last_message_preview": last_preview[:160],
                    "updated_at": datetime.now(timezone.utc),
                },
                "$inc": {"message_count": increment_messages},
            },
        )

    async def list_conversations_for_user(
        self, user_oid: ObjectId, limit: int = 50,
    ) -> list[dict]:
        cursor = (
            self.conv.find({"user_id": user_oid})
            .sort("updated_at", -1)
            .limit(limit)
        )
        return [doc async for doc in cursor]

    async def delete_conversation(
        self, conv_id: str | ObjectId, user_oid: ObjectId,
    ) -> bool:
        """Remove the conversation document and every message it owns.

        Returns True iff the conversation existed and belonged to the
        caller. We delete the conversation first (the ownership check)
        and only cascade to messages after that succeeds, so an attacker
        cannot clear someone else's transcripts by guessing an id.
        """
        oid = conv_id if isinstance(conv_id, ObjectId) else ObjectId(conv_id)
        result = await self.conv.delete_one({"_id": oid, "user_id": user_oid})
        if result.deleted_count == 0:
            return False
        await self.msg.delete_many({"conversation_id": oid})
        return True

    # ---- messages ----

    async def create_message(self, doc: dict[str, Any]) -> ObjectId:
        result = await self.msg.insert_one(doc)
        return result.inserted_id

    async def list_messages_for_conversation(
        self, conv_oid: ObjectId,
    ) -> list[dict]:
        cursor = self.msg.find({"conversation_id": conv_oid}).sort("created_at", 1)
        return [doc async for doc in cursor]
