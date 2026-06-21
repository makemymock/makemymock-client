"""Dedicated read-only Motor client for the mined catalog.

`patterns` and `pattern_assignments` live on the PYQ cluster
(`settings.PYQ_MONGO_URI` → `settings.PYQ_DB_NAME`), a different Mongo from the
backend's primary one, so this module keeps its own lazy client rather than
going through `config.database` / `DBDep`. Built once and shared for the
process lifetime; closed on app shutdown (see main.py).

Index creation is NOT done here — the standalone Pattern_Miner pipeline owns
the write side, including indexes.
"""

from __future__ import annotations

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from config.settings import settings

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


async def close_client() -> None:
    """Release the client. Called on app shutdown."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
