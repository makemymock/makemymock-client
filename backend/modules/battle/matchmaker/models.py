"""Pure data classes for matchmaking state.

Zero I/O, zero Redis, zero asyncio logic — just shapes. Kept isolated
so consumers that only need ``Player`` or ``Battle`` (like the game-loop
in ``service.py``) don't transitively pull in Redis.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from bson import ObjectId
from fastapi import WebSocket


@dataclass
class Player:
    """A participant in an active battle."""
    user_id: ObjectId       # Mongo ObjectId from the users collection
    username: str
    ws: Optional[WebSocket] = None
    score: int = 0
    correct_count: int = 0
    disconnected: bool = False
    # Round-by-round trace, filled in by the game loop.
    answers: list[dict] = field(default_factory=list)


@dataclass
class Battle:
    """Live state of a paired 1-vs-1 match."""
    battle_id: str
    player_a: Player
    player_b: Player
    questions: list[dict] = field(default_factory=list)   # raw catalog docs
    completion_event: asyncio.Event = field(default_factory=asyncio.Event)
    started_at: float = 0.0
    is_distributed: bool = False
    local_role: str = "a"       # "a" or "b" (which player is local to this container)
    is_coordinator: bool = True  # True if this container orchestrates question sampling & MongoDB save


@dataclass
class Waiter:
    """A player sitting in the queue waiting for an opponent.

    The ``future`` is resolved with the ``Battle`` once paired, or times
    out. The queue / invite managers own the lifecycle of these objects.
    """
    user: dict                 # raw user doc from Mongo
    ws: WebSocket
    future: asyncio.Future     # resolved with the Battle once paired
