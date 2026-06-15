"""Dedicated Motor client for the pattern miner's data.

The source PYQ catalog and the mined output both live on the PYQ cluster
(`settings.PYQ_MONGO_URI` → `settings.PYQ_DB_NAME`), which is a *different*
Mongo from the backend's primary one. So this module keeps its own lazy client
rather than going through `config.database` / `DBDep` — both the read API and
the offline jobs resolve their database here.

The client is built once on first use and shared for the process lifetime
(Motor clients are safe to share across the event loop's tasks).
"""

from __future__ import annotations

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING

from config.settings import settings
from modules.pattern_miner.constants import (
    ASSIGNMENTS_COLLECTION,
    CHECKPOINT_COLLECTION,
    PATTERNS_COLLECTION,
)

_client: Optional[AsyncIOMotorClient] = None


def get_pattern_miner_db() -> AsyncIOMotorDatabase:
    """The `adaptive_practice` database on the PYQ cluster. Raises if the URI
    isn't configured so the failure is obvious rather than a silent wrong-DB."""
    global _client
    if _client is None:
        if not settings.PYQ_MONGO_URI:
            raise RuntimeError(
                "PYQ_MONGO_URI is not configured; set it in backend/.env"
            )
        # tz_aware so pattern timestamps read back with UTC tzinfo, matching the
        # primary client's convention (see config/database.py).
        _client = AsyncIOMotorClient(
            settings.PYQ_MONGO_URI,
            uuidRepresentation="standard",
            tz_aware=True,
        )
    return _client[settings.PYQ_DB_NAME]


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """Create the miner's indexes on the PYQ cluster. Idempotent; the jobs call
    it before a live pass. `jee_mains_pyqs` is read-only here so it's left as-is.

    - patterns: unique (chapter, slug) so racing proposals can't both win; the
      plain (chapter) index backs the hot-path list_for_chapter read.
    - assignments: unique (question_id) so re-runs overwrite; (pattern_id) backs
      the coverage read + dedupe re-point.
    - checkpoints: unique (question_id) for resumability.
    """
    await db[PATTERNS_COLLECTION].create_index(
        [("chapter", ASCENDING), ("slug", ASCENDING)], unique=True,
    )
    await db[PATTERNS_COLLECTION].create_index([("chapter", ASCENDING)])
    await db[ASSIGNMENTS_COLLECTION].create_index(
        [("question_id", ASCENDING)], unique=True,
    )
    await db[ASSIGNMENTS_COLLECTION].create_index([("pattern_id", ASCENDING)])
    await db[CHECKPOINT_COLLECTION].create_index(
        [("question_id", ASCENDING)], unique=True,
    )


async def close_client() -> None:
    """Release the client. Safe to call on shutdown / at the end of a job."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
