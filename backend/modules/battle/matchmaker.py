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
