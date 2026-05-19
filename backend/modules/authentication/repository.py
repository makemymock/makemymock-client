from datetime import datetime
from typing import Any, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from modules.authentication.constants import OTPS_COLLECTION, USERS_COLLECTION


class UserRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.col = db[USERS_COLLECTION]

    async def get_by_email(self, email: str) -> Optional[dict[str, Any]]:
        return await self.col.find_one({"email": email.lower().strip()})

    async def get_by_username(self, username: str) -> Optional[dict[str, Any]]:
        return await self.col.find_one({"username": username.strip()})

    async def get_by_id(self, user_id: str | ObjectId) -> Optional[dict[str, Any]]:
        oid = user_id if isinstance(user_id, ObjectId) else ObjectId(user_id)
        return await self.col.find_one({"_id": oid})

    async def create(self, doc: dict[str, Any]) -> dict[str, Any]:
        result = await self.col.insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc

    async def mark_verified(self, user_id: ObjectId) -> None:
        await self.col.update_one(
            {"_id": user_id},
            {"$set": {"is_verified": True, "updated_at": datetime.utcnow()}},
        )

    async def exists_email(self, email: str) -> bool:
        return await self.col.count_documents({"email": email.lower().strip()}, limit=1) > 0

    async def exists_username(self, username: str) -> bool:
        return await self.col.count_documents({"username": username.strip()}, limit=1) > 0


class OTPRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.col = db[OTPS_COLLECTION]

    async def upsert(self, email: str, doc: dict[str, Any]) -> None:
        """Replace any existing OTP for this email with a fresh one."""
        await self.col.delete_many({"email": email.lower().strip()})
        await self.col.insert_one(doc)

    async def get_latest(self, email: str) -> Optional[dict[str, Any]]:
        return await self.col.find_one(
            {"email": email.lower().strip()},
            sort=[("created_at", -1)],
        )

    async def increment_attempts(self, otp_id: ObjectId) -> int:
        result = await self.col.find_one_and_update(
            {"_id": otp_id},
            {"$inc": {"attempts": 1}},
            return_document=True,
        )
        return int(result["attempts"]) if result else 0

    async def delete_for_email(self, email: str) -> None:
        await self.col.delete_many({"email": email.lower().strip()})
