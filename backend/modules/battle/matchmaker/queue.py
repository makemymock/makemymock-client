"""FIFO matchmaking queue backed by a Redis List.

Players are pushed onto the list when they connect. When a second player
arrives and the list already has an entry, we pop the waiting player,
build a ``Battle``, and resolve the first player's ``asyncio.Future``.

Falls back to an in-memory list when Redis is unavailable.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import WebSocket
from motor.motor_asyncio import AsyncIOMotorDatabase

from modules.battle.matchmaker.keys import (
    QUEUE_KEY,
    QUEUE_MEMBER_TTL,
    queue_membership,
)
from modules.battle.matchmaker.models import Battle, Player, Waiter

logger = logging.getLogger(__name__)


def _build_battle(first: Waiter, second: Waiter) -> Battle:
    """Compose a ``Battle`` from two paired waiters.

    ``first`` is the player who was already queued; ``second`` is the
    one whose arrival triggered the match.
    """
    from modules.battle.model import make_battle_id

    a = Player(
        user_id=first.user["_id"],
        username=first.user.get("username", "Player"),
        ws=first.ws,
    )
    b = Player(
        user_id=second.user["_id"],
        username=second.user.get("username", "Player"),
        ws=second.ws,
    )
    return Battle(battle_id=make_battle_id(), player_a=a, player_b=b)


async def _wait_match_or_disconnect(waiter: Waiter, timeout: float) -> Optional[Battle]:
    """Await match future while concurrently monitoring WebSocket disconnect.

    If the player closes their browser tab or disconnects while parked,
    wakes up immediately and unparks rather than leaving a stale waiter
    until the full timeout.
    """
    async def _detect_disconnect():
        try:
            while True:
                msg = await waiter.ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    return
        except Exception:
            return

    monitor_task = asyncio.create_task(_detect_disconnect())
    future_task = asyncio.create_task(asyncio.wait_for(waiter.future, timeout=timeout))
    try:
        done, pending = await asyncio.wait(
            [future_task, monitor_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
        if future_task in done and not future_task.cancelled() and future_task.exception() is None:
            return future_task.result()
        return None
    finally:
        monitor_task.cancel()


class MatchQueue:
    """FIFO matchmaking queue with Redis List storage and local Future
    signaling.

    Even though the queue lives in Redis, each player's ``WebSocket``
    and ``asyncio.Future`` are local to this process. A local
    ``_waiters`` dict maps ``user_id → Waiter`` so we can resolve
    Futures when a match is made.
    """

    def __init__(self, redis: Optional[object] = None) -> None:
        self._redis = redis
        # Local registry: user_id → Waiter (process-local WebSocket +
        # Future). Needed because Redis stores serializable data, but
        # the WebSocket and Future are in-process objects.
        self._waiters: dict[str, Waiter] = {}
        # In-memory fallback queue for when Redis is unavailable.
        self._local_queue: list[Waiter] = []
        self._lock = asyncio.Lock()

    async def enqueue(
        self,
        user: dict,
        ws: WebSocket,
        *,
        timeout: float,
        db: AsyncIOMotorDatabase,
        manager: object,  # BattleMatchmaker — import deferred to avoid circular
    ) -> Optional[Battle]:
        """Try to pair this user with someone already in the queue.

        If paired immediately: builds the Battle, spawns the game-loop
        task, notifies the waiting player, and returns the Battle.

        If nobody is waiting: parks this user and awaits ``timeout``
        seconds for an opponent. Returns ``None`` if it expires.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        waiter = Waiter(user=user, ws=ws, future=future)
        user_id = str(user["_id"])

        # Local import avoids a circular import at module load.
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
        battle = await _wait_match_or_disconnect(waiter, timeout=timeout)
        if battle is None:
            await self._cancel(user_id)
        return battle

    # ---- Redis path ----

    async def _try_redis_enqueue(
        self, user, user_id, waiter, db, manager, run_battle_loop,
    ) -> Optional[Battle]:
        """Attempt to pair via Redis. Returns a Battle or None (= parked)."""
        try:
            # Check if someone is already waiting.
            queue_len = await self._redis.llen(QUEUE_KEY)

            if queue_len and queue_len > 0:
                # Pop the oldest entry.
                raw = await self._redis.rpop(QUEUE_KEY)
                if raw:
                    entry = json.loads(raw) if isinstance(raw, str) else raw
                    other_uid = entry["user_id"]

                    # Don't match with ourselves (shouldn't happen but
                    # guard against stale queue entries).
                    if other_uid == user_id:
                        # Push ourselves back and park.
                        await self._redis.lpush(QUEUE_KEY, raw)
                    else:
                        # Clean up the other player's membership marker.
                        await self._redis.delete(queue_membership(other_uid))

                        # Resolve the other player's Future if they're
                        # in this process.
                        other_waiter = self._waiters.pop(other_uid, None)
                        if other_waiter is not None:
                            battle = _build_battle(other_waiter, waiter)
                            if not other_waiter.future.done():
                                other_waiter.future.set_result(battle)
                            # Spawn the game loop.
                            asyncio.create_task(
                                run_battle_loop(battle, db, manager),
                                name=f"battle-{battle.battle_id}",
                            )
                            return battle
                        else:
                            # The other player is in a different process
                            # (future multi-worker scenario). For now,
                            # treat as a miss and re-push their entry.
                            logger.warning(
                                "Popped user %s from Redis queue but "
                                "no local Waiter found — re-pushing.",
                                other_uid,
                            )
                            await self._redis.lpush(QUEUE_KEY, raw)

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
                battle = _build_battle(other, waiter)
                if not other.future.done():
                    other.future.set_result(battle)
                # Spawn the game loop.
                asyncio.create_task(
                    run_battle_loop(battle, db, manager),
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
                # Remove from Redis queue. LREM removes all occurrences
                # matching the value, but we need to know the value.
                # Simpler: just delete the membership marker and let the
                # stale entry be skipped on the next pop.
                await self._redis.delete(queue_membership(user_id))
            except Exception:
                logger.exception("Redis queue cancel failed")

        # Clean up local fallback queue.
        async with self._lock:
            self._local_queue = [
                w for w in self._local_queue
                if str(w.user["_id"]) != user_id
            ]
