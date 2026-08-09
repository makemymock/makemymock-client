"""Shared matchmaking helpers used by both public queue and private invites.

Consolidates local Battle composition, question serialization, Redis inbox
dispatch, and cross-container match polling into a single DRY module.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from modules.battle.matchmaker.keys import INBOX_TTL, player_inbox
from modules.battle.matchmaker.models import Battle, Player, Waiter

logger = logging.getLogger(__name__)


def build_local_battle(first: Waiter, second: Waiter) -> Battle:
    """Compose a ``Battle`` from two paired waiters in the same container process."""
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
    return Battle(
        battle_id=make_battle_id(),
        player_a=a,
        player_b=b,
        is_distributed=False,
        local_role="a",
        is_coordinator=True,
    )


def _to_json_compatible(val):
    if isinstance(val, ObjectId):
        return str(val)
    if hasattr(val, "isoformat"):
        return val.isoformat()
    if isinstance(val, dict):
        return {k: _to_json_compatible(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_to_json_compatible(v) for v in val]
    return val


def serialize_question_doc(q_doc: dict) -> dict:
    """Convert Mongo question document into JSON-serializable shape."""
    return _to_json_compatible(q_doc)


def deserialize_question_doc(q_dict: dict) -> dict:
    """Restore ObjectId from serialized question dictionary."""
    d = dict(q_dict)
    if "_id" in d and isinstance(d["_id"], str):
        try:
            d["_id"] = ObjectId(d["_id"])
        except Exception:
            pass
    return d


async def dispatch_remote_match(
    redis: object,
    recipient_uid: str,
    battle_id: str,
    questions: list[dict],
    opponent_user: dict,
) -> None:
    """Push a MATCHED event payload into the remote player's Redis inbox."""
    serialized_questions = [serialize_question_doc(q) for q in questions]
    inbox_msg = {
        "type": "matched",
        "battle_id": battle_id,
        "questions": serialized_questions,
        "opponent": {
            "user_id": str(opponent_user["_id"]),
            "username": opponent_user.get("username", "Player"),
        },
    }
    key = player_inbox(recipient_uid)
    await redis.lpush(key, json.dumps(inbox_msg))
    await redis.expire(key, INBOX_TTL)


async def wait_match_or_disconnect(
    waiter: Waiter,
    timeout: float,
    *,
    redis: Optional[object] = None,
    user_id: Optional[str] = None,
    db: Optional[AsyncIOMotorDatabase] = None,
    manager: Optional[object] = None,
    battle_tag: str = "battle",
) -> Optional[Battle]:
    """Await match future while concurrently monitoring WebSocket disconnect
    and remote Redis inbox notifications.
    """
    async def _detect_disconnect():
        try:
            while True:
                msg = await waiter.ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    return
        except Exception:
            return

    async def _poll_inbox():
        if redis is None or not user_id:
            await asyncio.Event().wait()
            return None
        inbox_key = player_inbox(user_id)
        while True:
            try:
                raw = await redis.rpop(inbox_key)
                if raw:
                    data = json.loads(raw) if isinstance(raw, str) else raw
                    if data.get("type") == "matched":
                        battle_id = data["battle_id"]
                        raw_questions = [deserialize_question_doc(q) for q in data["questions"]]
                        opp = data["opponent"]
                        player_a = Player(
                            user_id=waiter.user["_id"],
                            username=waiter.user.get("username", "Player"),
                            ws=waiter.ws,
                        )
                        player_b = Player(
                            user_id=ObjectId(opp["user_id"]),
                            username=opp.get("username", "Player"),
                            ws=None,
                        )
                        battle = Battle(
                            battle_id=battle_id,
                            player_a=player_a,
                            player_b=player_b,
                            questions=raw_questions,
                            is_distributed=True,
                            local_role="a",
                            is_coordinator=False,
                        )
                        if not waiter.future.done():
                            waiter.future.set_result(battle)
                        from modules.battle.service import run_battle_loop
                        asyncio.create_task(
                            run_battle_loop(battle, db, manager, redis=redis),
                            name=f"{battle_tag}-joiner-{battle.battle_id}",
                        )
                        return battle
            except Exception as exc:
                logger.debug("Inbox poll error for %s: %s", user_id, exc)
            await asyncio.sleep(0.08)

    monitor_task = asyncio.create_task(_detect_disconnect())
    future_task = asyncio.create_task(asyncio.wait_for(waiter.future, timeout=timeout))
    inbox_task = asyncio.create_task(_poll_inbox())

    try:
        done, pending = await asyncio.wait(
            [future_task, monitor_task, inbox_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
        if future_task in done and not future_task.cancelled() and future_task.exception() is None:
            return future_task.result()
        if inbox_task in done and not inbox_task.cancelled() and inbox_task.exception() is None:
            res = inbox_task.result()
            if res is not None:
                return res
        return None
    finally:
        monitor_task.cancel()
        inbox_task.cancel()
