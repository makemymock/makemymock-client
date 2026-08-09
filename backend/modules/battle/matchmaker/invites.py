"""Invite-code pairing for private "battle a friend" sessions.

Fundamentally different from the public queue: matches are keyed by an
invite code, not FIFO order. Kept separate from ``queue.py`` so the two
flows can't accidentally interfere.

Redis stores the host's info in a Hash; when the friend arrives, the
Hash is consumed and a Battle is built.

Falls back to an in-memory dict when Redis is unavailable.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import WebSocket
from motor.motor_asyncio import AsyncIOMotorDatabase

from modules.battle.matchmaker.keys import INVITE_TTL, invite_host
from modules.battle.matchmaker.models import Battle, Player, Waiter

logger = logging.getLogger(__name__)


def _build_battle(first: Waiter, second: Waiter) -> Battle:
    """Compose a ``Battle`` from two paired waiters."""
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
    """Await match future while concurrently monitoring WebSocket disconnect."""
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


class InviteMatchmaker:
    """Private matchmaking via invite codes.

    First connection with a code becomes the **host** (parked, waiting).
    Second connection with the same code becomes the **friend** and
    triggers the pairing.
    """

    def __init__(self, redis: Optional[object] = None) -> None:
        self._redis = redis
        # Local registry: code → Waiter (process-local WS + Future).
        self._hosts: dict[str, Waiter] = {}
        self._lock = asyncio.Lock()

    async def claim_invite(
        self,
        user: dict,
        ws: WebSocket,
        *,
        code: str,
        timeout: float,
        db: AsyncIOMotorDatabase,
        manager: object,
        invite_repo: object,
    ) -> Optional[Battle]:
        """Try to pair this user with the invite host.

        First caller parks as host; second caller pairs with the host
        and spawns the game loop.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        waiter = Waiter(user=user, ws=ws, future=future)
        user_id = str(user["_id"])

        from modules.battle.service import run_battle_loop

        spawned: Optional[Battle] = None

        if self._redis is not None:
            spawned = await self._try_redis_invite(
                user, user_id, waiter, code, db, manager,
                invite_repo, run_battle_loop,
            )
        else:
            spawned = await self._try_local_invite(
                user, user_id, waiter, code, db, manager,
                invite_repo, run_battle_loop,
            )

        if spawned is not None:
            return spawned

        # Host path: park and wait for the friend or disconnect.
        battle = await _wait_match_or_disconnect(waiter, timeout=timeout)
        if battle is None:
            await self._cancel(code, user_id)
        return battle

    # ---- Redis path ----

    async def _try_redis_invite(
        self, user, user_id, waiter, code, db, manager,
        invite_repo, run_battle_loop,
    ) -> Optional[Battle]:
        """Attempt to pair via Redis Hash."""
        key = invite_host(code)
        try:
            # Check if a host is already parked for this code.
            host_data = await self._redis.hgetall(key)

            if host_data and host_data.get("user_id") != user_id:
                # Friend arrived! Pair with the host.
                await self._redis.delete(key)

                host_waiter = self._hosts.pop(code, None)
                if host_waiter is not None:
                    battle = _build_battle(host_waiter, waiter)
                    if not host_waiter.future.done():
                        host_waiter.future.set_result(battle)

                    # Mark invite accepted + stamp battle id.
                    await self._mark_invite_accepted(
                        invite_repo, code, user, battle.battle_id,
                    )
                    asyncio.create_task(
                        run_battle_loop(battle, db, manager),
                        name=f"battle-invite-{battle.battle_id}",
                    )
                    return battle
                else:
                    logger.warning(
                        "Invite host for code=%s found in Redis but no "
                        "local Waiter — cannot pair.", code,
                    )
                    return None

            elif host_data and host_data.get("user_id") == user_id:
                # Same user reconnecting (tab refresh) — cancel old waiter and replace.
                old = self._hosts.get(code)
                if old is not None and not old.future.done():
                    old.future.cancel()
                self._hosts[code] = waiter
                return None

            else:
                # No host yet. This user becomes the host.
                await self._redis.hset(key, values={
                    "user_id": user_id,
                    "username": user.get("username", "Player"),
                })
                await self._redis.expire(key, INVITE_TTL)
                self._hosts[code] = waiter
                return None

        except Exception:
            logger.exception("Redis invite operation failed; falling back to local")
            return await self._try_local_invite(
                user, user_id, waiter, code, db, manager,
                invite_repo, run_battle_loop,
            )

    # ---- In-memory fallback ----

    async def _try_local_invite(
        self, user, user_id, waiter, code, db, manager,
        invite_repo, run_battle_loop,
    ) -> Optional[Battle]:
        """Pure in-memory path — identical to the old matchmaker logic."""
        async with self._lock:
            host = self._hosts.get(code)
            if host is not None and str(host.user["_id"]) != user_id:
                # Friend arrived. Pair with the host.
                del self._hosts[code]
                battle = _build_battle(host, waiter)
                if not host.future.done():
                    host.future.set_result(battle)

                await self._mark_invite_accepted(
                    invite_repo, code, user, battle.battle_id,
                )
                asyncio.create_task(
                    run_battle_loop(battle, db, manager),
                    name=f"battle-invite-{battle.battle_id}",
                )
                return battle

            elif host is not None and str(host.user["_id"]) == user_id:
                # Same user reconnecting — cancel old waiter and replace.
                if not host.future.done():
                    host.future.cancel()
                self._hosts[code] = waiter
                return None

            else:
                # This user becomes the host.
                self._hosts[code] = waiter
                return None

    # ---- Helpers ----

    @staticmethod
    async def _mark_invite_accepted(
        invite_repo, code: str, user: dict, battle_id: str,
    ) -> None:
        """Best-effort: stamp the invite doc as accepted. A Mongo hiccup
        here shouldn't block the battle."""
        try:
            await invite_repo.mark_accepted(
                code,
                invitee_oid=user["_id"],
                invitee_username=user.get("username") or "Player",
            )
            await invite_repo.attach_battle_id(code, battle_id)
        except Exception:
            logger.exception("Invite mark-accepted failed for code=%s", code)

    async def _cancel(self, code: str, user_id: str) -> None:
        """Remove a parked host on timeout/disconnect."""
        # Only remove if we are the parked host.
        host = self._hosts.get(code)
        if host is not None and str(host.user["_id"]) == user_id:
            self._hosts.pop(code, None)

        if self._redis is not None:
            try:
                key = invite_host(code)
                host_data = await self._redis.hgetall(key)
                if host_data and host_data.get("user_id") == user_id:
                    await self._redis.delete(key)
            except Exception:
                logger.exception("Redis invite cancel failed")
