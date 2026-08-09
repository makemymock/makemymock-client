"""FIFO matchmaking queue backed by a Redis List.

Players are pushed onto the list when they connect. When a second player
arrives and the list already has an entry, we pop the waiting player,
build a ``Battle``, and resolve the first player's ``asyncio.Future``.

Supports both local in-process and distributed cross-container pairing.
Falls back to an in-memory list when Redis is unavailable.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from bson import ObjectId
from fastapi import WebSocket
from motor.motor_asyncio import AsyncIOMotorDatabase

from modules.battle.constants import QUESTIONS_PER_BATTLE
from modules.battle.matchmaker.common import (
    build_local_battle,
    dispatch_remote_match,
    wait_match_or_disconnect,
)
from modules.battle.matchmaker.keys import (
    QUEUE_KEY,
    QUEUE_MEMBER_TTL,
    queue_membership,
)
from modules.battle.matchmaker.models import Battle, Player, Waiter

logger = logging.getLogger(__name__)


class MatchQueue:
    """FIFO matchmaking queue with Redis List storage and local Future
    signaling.
    """

    def __init__(self, redis: Optional[object] = None) -> None:
        self._redis = redis
        self._waiters: dict[str, Waiter] = {}
        self._local_queue: list[Waiter] = []
        self._lock = asyncio.Lock()

    async def enqueue(
        self,
        user: dict,
        ws: WebSocket,
        *,
        timeout: float,
        db: AsyncIOMotorDatabase,
        manager: object,
    ) -> Optional[Battle]:
        """Try to pair this user with someone already in the queue."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        waiter = Waiter(user=user, ws=ws, future=future)
        user_id = str(user["_id"])

        from modules.battle.service import run_battle_loop

        spawned: Optional[Battle] = None

        if self._redis is not None:
            spawned = await self._try_redis_enqueue(
                user, user_id, waiter, db, manager, run_battle_loop,
            )
        else:
            spawned = await self._try_local_enqueue(
                user, user_id, waiter, db, manager, run_battle_loop,
            )

        if spawned is not None:
            return spawned

        # Park and wait for an opponent or client disconnect.
        battle = await wait_match_or_disconnect(
            waiter,
            timeout=timeout,
            redis=self._redis,
            user_id=user_id,
            db=db,
            manager=manager,
            battle_tag="battle-queue",
        )
        if battle is None:
            await self._cancel(user_id)
        return battle

    # ---- Redis path ----

    async def _try_redis_enqueue(
        self, user, user_id, waiter, db, manager, run_battle_loop,
    ) -> Optional[Battle]:
        """Attempt to pair via Redis. Returns a Battle or None (= parked)."""
        try:
            queue_len = await self._redis.llen(QUEUE_KEY)

            if queue_len and queue_len > 0:
                raw = await self._redis.rpop(QUEUE_KEY)
                if raw:
                    entry = json.loads(raw) if isinstance(raw, str) else raw
                    other_uid = entry["user_id"]

                    if other_uid == user_id:
                        await self._redis.lpush(QUEUE_KEY, raw)
                    else:
                        await self._redis.delete(queue_membership(other_uid))

                        other_waiter = self._waiters.pop(other_uid, None)
                        if other_waiter is not None:
                            # 1. Local match on same container
                            battle = build_local_battle(other_waiter, waiter)
                            if not other_waiter.future.done():
                                other_waiter.future.set_result(battle)
                            asyncio.create_task(
                                run_battle_loop(battle, db, manager, redis=self._redis),
                                name=f"battle-{battle.battle_id}",
                            )
                            return battle
                        else:
                            # 2. Distributed match across containers!
                            from modules.battle.model import make_battle_id
                            from modules.battle.repository import BattleRepository

                            repo = BattleRepository(db)
                            questions = await repo.sample_random_questions(QUESTIONS_PER_BATTLE)
                            battle_id = make_battle_id()

                            await dispatch_remote_match(
                                self._redis,
                                recipient_uid=other_uid,
                                battle_id=battle_id,
                                questions=questions,
                                opponent_user=user,
                            )

                            player_a = Player(
                                user_id=ObjectId(other_uid),
                                username=entry.get("username", "Player"),
                                ws=None,
                            )
                            player_b = Player(
                                user_id=user["_id"],
                                username=user.get("username", "Player"),
                                ws=waiter.ws,
                            )
                            battle = Battle(
                                battle_id=battle_id,
                                player_a=player_a,
                                player_b=player_b,
                                questions=questions,
                                is_distributed=True,
                                local_role="b",
                                is_coordinator=True,
                            )
                            asyncio.create_task(
                                run_battle_loop(battle, db, manager, redis=self._redis),
                                name=f"battle-dist-coord-{battle.battle_id}",
                            )
                            return battle

            # No match. Push ourselves onto the queue.
            entry_json = json.dumps({
                "user_id": user_id,
                "username": user.get("username", "Player"),
            })
            await self._redis.lpush(QUEUE_KEY, entry_json)
            await self._redis.set(
                queue_membership(user_id), "1", ex=QUEUE_MEMBER_TTL,
            )
            self._waiters[user_id] = waiter
            return None

        except Exception:
            logger.exception("Redis queue operation failed; falling back to local")
            return await self._try_local_enqueue(
                user, user_id, waiter,
                db, manager, run_battle_loop,
            )

    # ---- In-memory fallback ----

    async def _try_local_enqueue(
        self, user, user_id, waiter, db, manager, run_battle_loop,
    ) -> Optional[Battle]:
        """Pure in-memory path — identical to the old matchmaker logic."""
        async with self._lock:
            other: Optional[Waiter] = None
            for w in self._local_queue:
                if str(w.user["_id"]) != user_id:
                    other = w
                    break
            if other is not None:
                self._local_queue.remove(other)
                battle = build_local_battle(other, waiter)
                if not other.future.done():
                    other.future.set_result(battle)
                asyncio.create_task(
                    run_battle_loop(battle, db, manager, redis=self._redis),
                    name=f"battle-{battle.battle_id}",
                )
                return battle
            else:
                self._local_queue.append(waiter)
                self._waiters[user_id] = waiter
                return None

    # ---- Cleanup ----

    async def _cancel(self, user_id: str) -> None:
        """Remove a user from the queue (timeout or disconnect)."""
        self._waiters.pop(user_id, None)

        if self._redis is not None:
            try:
                await self._redis.delete(queue_membership(user_id))
            except Exception:
                logger.exception("Redis queue cancel failed")

        async with self._lock:
            self._local_queue = [
                w for w in self._local_queue
                if str(w.user["_id"]) != user_id
            ]
