"""Invite-code pairing for private "battle a friend" sessions.

Fundamentally different from the public queue: matches are keyed by an
invite code, not FIFO order. Kept separate from ``queue.py`` so the two
flows can't accidentally interfere.

Supports both local in-process and distributed cross-container invite pairing.
Falls back to an in-memory dict when Redis is unavailable.
"""

from __future__ import annotations

import asyncio
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
from modules.battle.matchmaker.keys import INVITE_TTL, invite_host
from modules.battle.matchmaker.models import Battle, Player, Waiter

logger = logging.getLogger(__name__)


class InviteMatchmaker:
    """Private matchmaking via invite codes.

    First connection with a code becomes the **host** (parked, waiting).
    Second connection with the same code becomes the **friend** and
    triggers the pairing.
    """

    def __init__(self, redis: Optional[object] = None) -> None:
        self._redis = redis
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
        """Try to pair this user with the invite host."""
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
        battle = await wait_match_or_disconnect(
            waiter,
            timeout=timeout,
            redis=self._redis,
            user_id=user_id,
            db=db,
            manager=manager,
            battle_tag="battle-invite",
        )
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
            host_data = await self._redis.hgetall(key)

            if host_data and host_data.get("user_id") != user_id:
                # Friend arrived! Pair with the host.
                await self._redis.delete(key)
                host_uid = host_data["user_id"]

                host_waiter = self._hosts.pop(code, None)
                if host_waiter is not None:
                    # 1. Local match on same container
                    battle = build_local_battle(host_waiter, waiter)
                    if not host_waiter.future.done():
                        host_waiter.future.set_result(battle)

                    await self._mark_invite_accepted(
                        invite_repo, code, user, battle.battle_id,
                    )
                    asyncio.create_task(
                        run_battle_loop(battle, db, manager, redis=self._redis),
                        name=f"battle-invite-{battle.battle_id}",
                    )
                    return battle
                else:
                    # 2. Distributed invite match across containers!
                    from modules.battle.model import make_battle_id
                    from modules.battle.repository import BattleRepository

                    repo = BattleRepository(db)
                    questions = await repo.sample_random_questions(QUESTIONS_PER_BATTLE)
                    battle_id = make_battle_id()

                    await dispatch_remote_match(
                        self._redis,
                        recipient_uid=host_uid,
                        battle_id=battle_id,
                        questions=questions,
                        opponent_user=user,
                    )

                    await self._mark_invite_accepted(
                        invite_repo, code, user, battle_id,
                    )

                    player_a = Player(
                        user_id=ObjectId(host_uid),
                        username=host_data.get("username", "Player"),
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
                        name=f"battle-invite-coord-{battle.battle_id}",
                    )
                    return battle

            elif host_data and host_data.get("user_id") == user_id:
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
                del self._hosts[code]
                battle = build_local_battle(host, waiter)
                if not host.future.done():
                    host.future.set_result(battle)

                await self._mark_invite_accepted(
                    invite_repo, code, user, battle.battle_id,
                )
                asyncio.create_task(
                    run_battle_loop(battle, db, manager, redis=self._redis),
                    name=f"battle-invite-{battle.battle_id}",
                )
                return battle

            elif host is not None and str(host.user["_id"]) == user_id:
                old = self._hosts.get(code)
                if old is not None and not old.future.done():
                    old.future.cancel()
                self._hosts[code] = waiter
                return None

            else:
                self._hosts[code] = waiter
                return None

    # ---- Helpers ----

    async def _mark_invite_accepted(
        self, invite_repo: object, code: str, friend_user: dict, battle_id: str,
    ) -> None:
        """Stamp the invite doc as accepted with the friend's user ID and
        the generated battle ID. Best-effort — failure must not kill match.
        """
        try:
            if hasattr(invite_repo, "mark_accepted"):
                await invite_repo.mark_accepted(
                    code, friend_user["_id"], battle_id,
                )
        except Exception:
            logger.exception("Failed to mark invite %s accepted in DB", code)

    async def _cancel(self, code: str, user_id: str) -> None:
        """Remove a host's parked waiter on timeout or disconnect."""
        self._hosts.pop(code, None)

        if self._redis is not None:
            try:
                key = invite_host(code)
                host_data = await self._redis.hgetall(key)
                if host_data and host_data.get("user_id") == user_id:
                    await self._redis.delete(key)
            except Exception:
                logger.exception("Redis invite cancel failed")
