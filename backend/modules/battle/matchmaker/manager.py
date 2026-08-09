"""BattleMatchmaker — thin orchestrator composing slots, queue, and invites.

This class is the **only** public API the rest of the battle module
interacts with. Its method signatures are identical to the old
monolithic ``matchmaker.py`` so consumers don't need any changes.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import WebSocket
from motor.motor_asyncio import AsyncIOMotorDatabase

from modules.battle.matchmaker.invites import InviteMatchmaker
from modules.battle.matchmaker.models import Battle
from modules.battle.matchmaker.queue import MatchQueue
from modules.battle.matchmaker.slots import SlotManager

logger = logging.getLogger(__name__)


class BattleMatchmaker:
    """Orchestrates slot claiming, public queue matching, and invite
    pairing. All Redis interaction is delegated to the sub-managers.
    """

    def __init__(self, redis: Optional[object] = None) -> None:
        self._redis = redis
        self._slots = SlotManager(redis)
        self._queue = MatchQueue(redis)
        self._invites = InviteMatchmaker(redis)

    def set_redis(self, redis: Optional[object]) -> None:
        """Late-bind the Redis client after app startup.

        The ``manager`` singleton is created at import time (before the
        lifespan runs ``connect_to_redis``). This method lets ``main.py``
        inject the live client once it's available.
        """
        self._redis = redis
        self._slots = SlotManager(redis)
        self._queue = MatchQueue(redis)
        self._invites = InviteMatchmaker(redis)

    # ---- Slot management ----

    async def claim_slot(self, user_id: str) -> bool:
        """Reserve this user as 'in flight' (queued or battling).

        Returns ``False`` if the user already has an active session.
        """
        return await self._slots.claim(user_id)

    async def release_slot(self, user_id: str) -> None:
        """Free this user's slot."""
        await self._slots.release(user_id)

    # ---- Public queue ----

    async def enqueue(
        self,
        user: dict,
        ws: WebSocket,
        *,
        timeout: float,
        db: AsyncIOMotorDatabase,
    ) -> Optional[Battle]:
        """Try to pair this user with someone in the public queue."""
        return await self._queue.enqueue(
            user, ws, timeout=timeout, db=db, manager=self,
        )

    # ---- Invite pairing ----

    async def claim_invite(
        self,
        user: dict,
        ws: WebSocket,
        *,
        code: str,
        timeout: float,
        db: AsyncIOMotorDatabase,
        invite_repo: object,
    ) -> Optional[Battle]:
        """Private matchmaking via invite code."""
        return await self._invites.claim_invite(
            user, ws,
            code=code,
            timeout=timeout,
            db=db,
            manager=self,
            invite_repo=invite_repo,
        )
