"""Upstash Redis (REST) client lifecycle.

Mirrors the pattern in ``config/database.py`` — init on startup, access
via ``get_redis()``, and a no-op teardown (REST is stateless).

When ``UPSTASH_REDIS_REST_URL`` is blank the client stays ``None``.
Callers must check ``get_redis() is not None`` and fall back to in-memory
behaviour when Redis is unconfigured (local dev).
"""

from __future__ import annotations

import logging
from typing import Optional

from config.settings import settings

logger = logging.getLogger(__name__)

# Optional import — the package may not be installed in minimal test envs.
try:
    from upstash_redis.asyncio import Redis as UpstashRedis
except ImportError:  # pragma: no cover
    UpstashRedis = None  # type: ignore[assignment,misc]

_redis: Optional["UpstashRedis"] = None  # type: ignore[type-arg]


async def connect_to_redis() -> None:
    """Initialise the module-level Upstash client and health-check it."""
    global _redis

    url = settings.UPSTASH_REDIS_REST_URL
    token = settings.UPSTASH_REDIS_REST_TOKEN
    if not url or not token:
        logger.info("Upstash Redis not configured — matchmaking will use in-memory state.")
        return
    if UpstashRedis is None:
        logger.warning("upstash-redis package not installed; skipping Redis init.")
        return

    _redis = UpstashRedis(url=url, token=token)
    try:
        pong = await _redis.ping()
        logger.info("Upstash Redis connected (PING → %s).", pong)
    except Exception:
        logger.exception("Upstash Redis ping failed — falling back to in-memory.")
        _redis = None


async def close_redis_connection() -> None:
    """No-op for Upstash REST (stateless HTTP), but keeps the lifecycle
    symmetric with ``close_mongo_connection``."""
    global _redis
    _redis = None


def get_redis() -> Optional["UpstashRedis"]:  # type: ignore[type-arg]
    """Return the shared Upstash client, or ``None`` when unconfigured."""
    return _redis
