"""Mongo document factories for SolverX."""

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_conversation_doc(
    *,
    user_id: ObjectId,
    mode: str,
    title: str,
) -> dict[str, Any]:
    now = now_utc()
    return {
        "user_id": user_id,
        "mode": mode,
        "title": title,
        "message_count": 0,
        "last_message_preview": "",
        "created_at": now,
        "updated_at": now,
    }


def new_message_doc(
    *,
    conversation_id: ObjectId,
    role: str,
    text: str = "",
    blocks: list[dict] | None = None,
    topic: dict | None = None,
    insights: list[dict] | None = None,
    complexity_mode: str | None = None,
    image_data_url: str | None = None,
) -> dict[str, Any]:
    return {
        "conversation_id": conversation_id,
        "role": role,
        "text": text,
        "blocks": blocks or [],
        "topic": topic,
        "insights": insights or [],
        "complexity_mode": complexity_mode,
        # Base64 data URL (e.g. "data:image/png;base64,iVBORw…").
        # Stored on user messages so the transcript can render the
        # original screenshot when a saved conversation is reopened.
        "image_data_url": image_data_url,
        "created_at": now_utc(),
    }
