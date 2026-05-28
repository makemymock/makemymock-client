from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from modules.authentication.constants import STUDENT_PROFILES_COLLECTION


class ProfileRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.col = db[STUDENT_PROFILES_COLLECTION]

    async def get_by_user_id(self, user_id: ObjectId) -> Optional[dict[str, Any]]:
        return await self.col.find_one({"user_id": user_id})

    async def create(self, doc: dict[str, Any]) -> dict[str, Any]:
        result = await self.col.insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc

    async def update(self, user_id: ObjectId, updates: dict[str, Any]) -> Optional[dict[str, Any]]:
        updates = {**updates, "updated_at": datetime.now(timezone.utc)}
        return await self.col.find_one_and_update(
            {"user_id": user_id},
            {"$set": updates},
            return_document=True,
        )

    async def add_tour_completed(
        self, user_id: ObjectId, slug: str
    ) -> Optional[dict[str, Any]]:
        return await self.col.find_one_and_update(
            {"user_id": user_id},
            {
                "$addToSet": {"tours_completed": slug},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
            return_document=True,
        )
