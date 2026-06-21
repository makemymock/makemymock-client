"""Motor access to the PYQ cluster for the pattern-learning feature.

One lazy client to `PYQ_MONGO_URI`, exposing two databases on it:
  * the read-only catalog (`PYQ_DB_NAME` / adaptive_practice) — patterns,
    assignments, questions; populated by the standalone Pattern_Miner pipeline;
  * the progress DB (`PYQ_PROGRESS_DB_NAME` / pattern_learning) — this module's
    own per-student attempt records.

Both live on the PYQ cluster, separate from the backend's primary Mongo. The
attempts index is created at app startup via `ensure_indexes`.
"""

from __future__ import annotations

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING

from config.settings import settings
from modules.pattern_learning.constants import ATTEMPTS_COLLECTION

_client: Optional[AsyncIOMotorClient] = None


def _get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        if not settings.PYQ_MONGO_URI:
            raise RuntimeError(
                "PYQ_MONGO_URI is not configured; set it in backend/.env"
            )
        _client = AsyncIOMotorClient(
            settings.PYQ_MONGO_URI,
            uuidRepresentation="standard",
            tz_aware=True,
        )
    return _client


def get_catalog_db() -> AsyncIOMotorDatabase:
    """Read-only mined catalog (patterns / assignments / jee_mains_pyqs)."""
    return _get_client()[settings.PYQ_DB_NAME]


def get_progress_db() -> AsyncIOMotorDatabase:
    """Per-student pattern-path progress (this module owns it)."""
    return _get_client()[settings.PYQ_PROGRESS_DB_NAME]


async def ensure_indexes() -> None:
    """One attempt per (student, question); plus a (student, chapter) index for
    the per-chapter progress reads. Called once at app startup."""
    db = get_progress_db()
    await db[ATTEMPTS_COLLECTION].create_index(
        [("user_id", ASCENDING), ("question_id", ASCENDING)], unique=True,
    )
    await db[ATTEMPTS_COLLECTION].create_index(
        [("user_id", ASCENDING), ("chapter", ASCENDING)],
    )
    await db[ATTEMPTS_COLLECTION].create_index(
        [("user_id", ASCENDING), ("pattern_id", ASCENDING)],
    )


async def close_client() -> None:
    """Release the client on app shutdown."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
