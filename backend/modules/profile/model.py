from datetime import datetime, timezone
from typing import Any

from bson import ObjectId


def new_profile_doc(*, user_id: ObjectId, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": user_id,
        **data,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
