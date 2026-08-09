"""Distributed slot manager — prevents duplicate battle/queue sessions.

Uses Redis ``SET … NX EX`` to atomically claim a user slot with a TTL
safety net. If the server crashes mid-battle without calling ``release``,
the key auto-expires so the user isn't permanently locked out.

Falls back to an in-memory ``set`` when Redis is unavailable.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from modules.battle.matchmaker.keys import SLOT_TTL, active_slot

logger = logging.getLogger(__name__)


class SlotManager:
    """Claim / release a per-user "in-flight" slot.

    At most one slot per user_id is allowed at a time. This prevents the
    same student from opening two battle tabs simultaneously.
    """

    def __init__(self, redis: Optional[object] = None) -> None:
        self._redis = redis
        # In-memory fallback for local dev without Redis.
        self._local: set[str] = set()
        self._lock = asyncio.Lock()

    async def claim(self, user_id: str) -> bool:
        """Reserve this user as 'in flight' (queued or battling).

        Returns ``True`` if the slot was claimed, ``False`` if the user
        already has an active session.
        """
        if self._redis is not None:
            try:
                # SET key "1" NX EX 600 → returns True if set, False/None if exists
                result = await self._redis.set(
                    active_slot(user_id), "1", nx=True, ex=SLOT_TTL,
                )
                return bool(result)
            except Exception:
                logger.exception("Redis slot claim failed; falling back to local")

        # In-memory fallback
        async with self._lock:
            if user_id in self._local:
                return False
            self._local.add(user_id)
            return True

    async def release(self, user_id: str) -> None:
        """Free this user's slot so they can queue again."""
        if self._redis is not None:
            try:
                await self._redis.delete(active_slot(user_id))
            except Exception:
                logger.exception("Redis slot release failed")

        # Always clean up local state too (defense in depth).
        self._local.discard(user_id)
