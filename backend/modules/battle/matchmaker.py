"""In-memory 1v1 matchmaking and live battle state.

A single module-level `manager` is shared across all WebSocket connections
in this process. Works fine for single-instance deployments. When the
backend is scaled to multiple workers / pods, this needs to move to Redis
pub/sub + a shared queue — but we don't burn that complexity today.

Concurrency model:
  - One asyncio.Lock guards the queue and active-user set.
  - When a second player arrives and a match is made, the matchmaker spawns
    a single `run_battle_loop` background task that owns both WebSockets.
  - Both WS handlers (one per player) just await `battle.completion_event`
    after enqueue returns — they only exist to keep the WS open.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from bson import ObjectId
from fastapi import WebSocket
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes — describe a player in the queue, an active player in a
# battle, and the battle itself.
# ---------------------------------------------------------------------------

@dataclass
class Player:
    user_id: ObjectId       # Mongo ObjectId from the users collection
    username: str
    ws: WebSocket
    score: int = 0
    correct_count: int = 0
    disconnected: bool = False
    # Round-by-round trace, filled in by the game loop.
    answers: list[dict] = field(default_factory=list)


@dataclass
class Battle:
    battle_id: str
    player_a: Player
    player_b: Player
    questions: list[dict] = field(default_factory=list)   # raw catalog docs
    completion_event: asyncio.Event = field(default_factory=asyncio.Event)
    started_at: float = 0.0


@dataclass
class _Waiter:
    """A player sitting in the queue waiting for an opponent."""
    user: dict                 # raw user doc from Mongo
    ws: WebSocket
    future: asyncio.Future     # resolved with the Battle once paired


# ---------------------------------------------------------------------------
# Matchmaker
# ---------------------------------------------------------------------------

class BattleMatchmaker:
    def __init__(self) -> None:
        self._queue: list[_Waiter] = []
        self._lock = asyncio.Lock()
        # user_id (str) → role tag. Used to reject duplicate connections
        # (same user opening two tabs).
        self._active: set[str] = set()
        # invite_code → _Waiter sitting on the host-side of a private
        # battle, waiting for the invited friend to connect with the
        # same code. Separate from the public queue so random matchmaker
        # joiners never accidentally pair with an invite host.
        self._invite_hosts: dict[str, _Waiter] = {}

    # ---- bookkeeping ----

    async def claim_slot(self, user_id: str) -> bool:
        """Reserve this user as 'in flight' (queued or battling).

        Returns False if the user already has an active session.
        """
        async with self._lock:
            if user_id in self._active:
                return False
            self._active.add(user_id)
            return True

    def release_slot(self, user_id: str) -> None:
        self._active.discard(user_id)

    # ---- enqueue ----

    async def enqueue(
        self,
        user: dict,
        ws: WebSocket,
        *,
        timeout: float,
        db: AsyncIOMotorDatabase,
    ) -> Optional[Battle]:
        """Try to pair this user with someone already in the queue.

        If paired immediately: builds the Battle, spawns the game-loop task,
        notifies the waiting player, and returns the Battle to the caller.

        If nobody else is waiting: parks this user in the queue and awaits
        `timeout` seconds for an opponent. Returns None if it expires.
        """
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        waiter = _Waiter(user=user, ws=ws, future=future)

        # Local import avoids a circular import at module load.
        from modules.battle.service import run_battle_loop

        spawned: Optional[Battle] = None
        async with self._lock:
            # Look for an opponent that isn't us.
            other: Optional[_Waiter] = None
            for w in self._queue:
                if str(w.user["_id"]) != str(user["_id"]):
                    other = w
                    break
            if other is not None:
                self._queue.remove(other)
                battle = _build_battle(other, waiter)
                # Wake the other player up with the battle reference.
                if not other.future.done():
                    other.future.set_result(battle)
                spawned = battle
            else:
                self._queue.append(waiter)

        if spawned is not None:
            # Spawn the game loop OUTSIDE the lock — it does network I/O.
            asyncio.create_task(
                run_battle_loop(spawned, db, self),
                name=f"battle-{spawned.battle_id}",
            )
            return spawned

        # Park and wait.
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            async with self._lock:
                if waiter in self._queue:
                    self._queue.remove(waiter)
            return None
        except asyncio.CancelledError:
            async with self._lock:
                if waiter in self._queue:
                    self._queue.remove(waiter)
            raise

    # ---- invite pair-up ----

    async def claim_invite(
        self,
        user: dict,
        ws: WebSocket,
        *,
        code: str,
        timeout: float,
        db: AsyncIOMotorDatabase,
        invite_repo,
    ) -> Optional[Battle]:
        """Private analog of `enqueue` driven by invite codes.

        First connection with `code` becomes the host (parked, waits for
        the friend). Second connection with the same `code` pairs with
        the host and spawns the game loop just like normal matchmaking.

        `invite_repo` is a `BattleInviteRepository` instance — passed in
        so we can stamp the resulting `battle_id` onto the invite doc
        for audit (and so an inviter who refreshes their browser can
        recover the battle id without re-prompting).
        """
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        waiter = _Waiter(user=user, ws=ws, future=future)

        # Local import keeps the run_battle_loop dependency lazy.
        from modules.battle.service import run_battle_loop

        spawned: Optional[Battle] = None
        async with self._lock:
            host = self._invite_hosts.get(code)
            if host is not None and str(host.user["_id"]) != str(user["_id"]):
                # Friend arrived. Pair with the host.
                del self._invite_hosts[code]
                battle = _build_battle(host, waiter)
                if not host.future.done():
                    host.future.set_result(battle)
                spawned = battle
            elif host is not None and str(host.user["_id"]) == str(user["_id"]):
                # Same user reconnecting (e.g. tab refresh) — replace
                # the parked waiter with the new socket so the friend's
                # eventual arrival pairs with the live WS.
                self._invite_hosts[code] = waiter
            else:
                # No one is parked yet; this user becomes the host.
                self._invite_hosts[code] = waiter

        if spawned is not None:
            # Mark the invite as accepted + stamp the battle id BEFORE
            # spawning the loop, so the inviter's polling (if any) can
            # observe the transition immediately. Best-effort — a Mongo
            # hiccup here shouldn't block the battle.
            try:
                await invite_repo.mark_accepted(
                    code,
                    invitee_oid=user["_id"],
                    invitee_username=user.get("username") or "Player",
                )
                await invite_repo.attach_battle_id(code, spawned.battle_id)
            except Exception:  # noqa: BLE001
                logger.exception("Invite mark-accepted failed for code=%s", code)
            asyncio.create_task(
                run_battle_loop(spawned, db, self),
                name=f"battle-invite-{spawned.battle_id}",
            )
            return spawned

        # Host path: park and wait for the friend.
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            async with self._lock:
                if self._invite_hosts.get(code) is waiter:
                    del self._invite_hosts[code]
            return None
        except asyncio.CancelledError:
            async with self._lock:
                if self._invite_hosts.get(code) is waiter:
                    del self._invite_hosts[code]
            raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_battle(first: _Waiter, second: _Waiter) -> Battle:
    """Compose a Battle from the two paired waiters.

    `first` is the player who was already queued (joined earlier); `second`
    is the one whose arrival triggered the match.
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


# Module-level singleton — imported by the controller and service.
manager = BattleMatchmaker()
