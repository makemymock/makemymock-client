from datetime import datetime
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.exceptions import InvalidTourSlug, ProfileAlreadyExists, ProfileNotFound
from modules.profile.constants import VALID_TOUR_SLUGS
from modules.profile.model import new_profile_doc
from modules.profile.repository import ProfileRepository
from modules.profile.schema import (
    ProfileCreateRequest,
    ProfileResponse,
    ProfileUpdateRequest,
)


class ProfileService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.repo = ProfileRepository(db)

    @staticmethod
    def _to_response(doc: dict[str, Any]) -> ProfileResponse:
        dob = doc["date_of_birth"]
        # Mongo stores dates as datetime; coerce back to date for the response.
        if isinstance(dob, datetime):
            dob = dob.date()
        return ProfileResponse(
            id=str(doc["_id"]),
            user_id=str(doc["user_id"]),
            full_name=doc["full_name"],
            date_of_birth=dob,
            class_grade=doc["class_grade"],
            target_exam=doc["target_exam"],
            state=doc["state"],
            school_name=doc["school_name"],
            city=doc["city"],
            preferred_language=doc["preferred_language"],
            phone_number=doc["phone_number"],
            gender=doc["gender"],
            tours_completed=doc.get("tours_completed", []),
            created_at=doc["created_at"],
            updated_at=doc.get("updated_at", doc["created_at"]),
        )

    @staticmethod
    def _serialize_payload(data: dict[str, Any]) -> dict[str, Any]:
        """Convert date -> datetime for Mongo, and enum -> str."""
        cleaned: dict[str, Any] = {}
        for k, v in data.items():
            if v is None:
                continue
            if hasattr(v, "value"):  # Enum
                cleaned[k] = v.value
            elif k == "date_of_birth":
                cleaned[k] = datetime.combine(v, datetime.min.time())
            else:
                cleaned[k] = v
        return cleaned

    async def create(self, user_id: ObjectId, payload: ProfileCreateRequest) -> ProfileResponse:
        if await self.repo.get_by_user_id(user_id) is not None:
            raise ProfileAlreadyExists()
        doc = new_profile_doc(
            user_id=user_id,
            data=self._serialize_payload(payload.model_dump()),
        )
        await self.repo.create(doc)
        return self._to_response(doc)

    async def get_mine(self, user_id: ObjectId) -> ProfileResponse:
        doc = await self.repo.get_by_user_id(user_id)
        if doc is None:
            raise ProfileNotFound()
        return self._to_response(doc)

    async def update(self, user_id: ObjectId, payload: ProfileUpdateRequest) -> ProfileResponse:
        updates = self._serialize_payload(payload.model_dump(exclude_unset=True))
        if not updates:
            doc = await self.repo.get_by_user_id(user_id)
            if doc is None:
                raise ProfileNotFound()
            return self._to_response(doc)
        doc = await self.repo.update(user_id, updates)
        if doc is None:
            raise ProfileNotFound()
        return self._to_response(doc)

    async def complete_tour(self, user_id: ObjectId, slug: str) -> ProfileResponse:
        if slug not in VALID_TOUR_SLUGS:
            raise InvalidTourSlug()
        doc = await self.repo.add_tour_completed(user_id, slug)
        if doc is None:
            raise ProfileNotFound()
        return self._to_response(doc)
