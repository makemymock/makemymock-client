"""FastAPI routes for the 1-vs-1 battle feature.

REST:
  GET  /battle/history         — your recent battles
  GET  /battle/{battle_id}     — replay one battle (must be a participant)

WebSocket:
  WS  /battle/ws?token=<jwt>   — join the queue and play

WS message protocol (server → client):
  - {type: "queued"}
  - {type: "matched", battle_id, opponent: {username}, questions_count,
                       time_per_question}
  - {type: "countdown", value}
  - {type: "question", index, total, question_id, question_text,
                       options:[{key, text}], difficulty, time_limit_seconds}
  - {type: "opponent_answered", question_id}
  - {type: "question_result", question_id, correct_option,
                              your_answer, your_correct, your_score_delta,
                              your_total_score, opponent_answer,
                              opponent_correct, opponent_score_delta,
                              opponent_total_score}
  - {type: "battle_complete", battle_id, result:"win"|"loss"|"draw",
                              your_score, your_correct, opponent_score,
                              opponent_correct, opponent_username, rounds_played}
  - {type: "queue_timeout"}
  - {type: "error", message}

WS message protocol (client → server):
  - {type: "submit_answer", question_id, selected_option:"A"|"B"|"C"|"D"}
"""

from __future__ import annotations

import logging
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from core.dependencies import CurrentVerifiedUser, DBDep
from core.exceptions import AppException, InvalidToken
from core.jwt_handler import decode_token
from modules.battle.constants import (
    QUEUE_TIMEOUT_SECONDS,
    WS_CLOSE_DUPLICATE,
    WS_CLOSE_INTERNAL,
    WS_CLOSE_UNAUTHORIZED,
)
from modules.battle.matchmaker import manager
from modules.battle.repository import BattleRepository
from modules.battle.schema import (
    BattleDetailResponse,
    BattleHistoryItem,
    BattleHistoryResponse,
    BattleOption,
    BattlePlayerSummary,
    BattleRoundDetail,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/battle", tags=["Battle"])


# ---------------------------------------------------------------------------
# REST — history + detail
# ---------------------------------------------------------------------------

@router.get(
    "/history",
    response_model=BattleHistoryResponse,
    summary="List the current user's recent battles",
)
async def get_history(
    user: CurrentVerifiedUser, db: DBDep,
) -> BattleHistoryResponse:
    repo = BattleRepository(db)
    docs = await repo.list_user_battles(user["_id"])
    items: list[BattleHistoryItem] = []
    for d in docs:
        you, opp, result = _split_perspective(d, user["_id"])
        items.append(BattleHistoryItem(
            _id=d["_id"],
            completed_at=d["completed_at"],
            questions_count=int(d.get("questions_count") or 0),
            you=you,
            opponent=opp,
            result=result,
        ))
    return BattleHistoryResponse(items=items)


@router.get(
    "/{battle_id}",
    response_model=BattleDetailResponse,
    summary="Fetch a single battle from the requesting user's perspective",
)
async def get_battle(
    battle_id: str, user: CurrentVerifiedUser, db: DBDep,
) -> BattleDetailResponse:
    repo = BattleRepository(db)
    doc = await repo.get_battle(battle_id, user["_id"])
    if doc is None:
        raise AppException("Battle not found.", status.HTTP_404_NOT_FOUND)
    you, opp, result = _split_perspective(doc, user["_id"])
    is_a = doc["player_a"]["user_id"] == user["_id"]
    rounds: list[BattleRoundDetail] = []
    for r in doc.get("rounds", []):
        rounds.append(BattleRoundDetail(
            index=int(r.get("index", 0)),
            question_text=r.get("question_text", ""),
            options=[BattleOption(**o) for o in r.get("options", [])],
            correct_option=r.get("correct_option", ""),
            your_answer=r.get("player_a_answer") if is_a else r.get("player_b_answer"),
            your_correct=bool(r.get("player_a_correct") if is_a else r.get("player_b_correct")),
            your_score_delta=int(r.get("player_a_score_delta") if is_a else r.get("player_b_score_delta") or 0),
            opponent_answer=r.get("player_b_answer") if is_a else r.get("player_a_answer"),
            opponent_correct=bool(r.get("player_b_correct") if is_a else r.get("player_a_correct")),
            opponent_score_delta=int(r.get("player_b_score_delta") if is_a else r.get("player_a_score_delta") or 0),
        ))
    return BattleDetailResponse(
        battle_id=doc["_id"],
        completed_at=doc["completed_at"],
        questions_count=int(doc.get("questions_count") or 0),
        you=you,
        opponent=opp,
        result=result,
        rounds=rounds,
    )


def _split_perspective(doc: dict, user_oid: ObjectId) -> tuple[
    BattlePlayerSummary, BattlePlayerSummary, str
]:
    a = doc["player_a"]
    b = doc["player_b"]
    is_a = a["user_id"] == user_oid
    me = a if is_a else b
    opp = b if is_a else a
    you = BattlePlayerSummary(
        user_id=str(me["user_id"]),
        username=me.get("username", ""),
        score=int(me.get("score", 0)),
        correct_count=int(me.get("correct_count", 0)),
    )
    opponent = BattlePlayerSummary(
        user_id=str(opp["user_id"]),
        username=opp.get("username", ""),
        score=int(opp.get("score", 0)),
        correct_count=int(opp.get("correct_count", 0)),
    )
    winner = doc.get("winner_user_id")
    if winner is None:
        result = "draw"
    elif winner == user_oid:
        result = "win"
    else:
        result = "loss"
    return you, opponent, result


# ---------------------------------------------------------------------------
# WebSocket — matchmaking + live battle
# ---------------------------------------------------------------------------

@router.websocket("/ws")
async def battle_ws(
    websocket: WebSocket,
    db: DBDep,
    token: str = Query(..., description="JWT access token"),
):
    # Accept first so we can send a JSON `error` message back on auth /
    # duplicate-slot failures. Pre-accept close gives the browser an opaque
    # HTTP 403 with no payload, which becomes a useless "Lost connection"
    # error on the client.
    await websocket.accept()

    user = await _authenticate(token, db)
    if user is None:
        logger.info("Battle WS: auth failed (token invalid or user missing)")
        await _reject(websocket, WS_CLOSE_UNAUTHORIZED,
                      "Your session has expired. Please log in again.")
        return
    if not user.get("is_verified", False):
        logger.info("Battle WS: user %s is not verified", user.get("_id"))
        await _reject(websocket, WS_CLOSE_UNAUTHORIZED,
                      "Please verify your email before joining a battle.")
        return

    user_id = str(user["_id"])
    if not await manager.claim_slot(user_id):
        logger.info("Battle WS: duplicate slot for user %s", user_id)
        await _reject(websocket, WS_CLOSE_DUPLICATE,
                      "You're already in a battle or queue on another tab.")
        return

    try:
        await websocket.send_json({"type": "queued"})
        battle = await manager.enqueue(
            user, websocket,
            timeout=QUEUE_TIMEOUT_SECONDS,
            db=db,
        )
        if battle is None:
            # Released by enqueue's timeout cleanup path is fine — we own
            # the slot release below.
            try:
                await websocket.send_json({"type": "queue_timeout"})
            finally:
                manager.release_slot(user_id)
                await websocket.close()
            return

        # Paired. The run_battle_loop task drives the WS from here. We
        # just keep the coroutine alive until the battle finishes.
        await battle.completion_event.wait()
    except WebSocketDisconnect:
        # Player bailed; if a battle is running, the loop will detect
        # disconnect and end gracefully.
        manager.release_slot(user_id)
        return
    except Exception:
        logger.exception("battle_ws error for user %s", user_id)
        manager.release_slot(user_id)
        try:
            await websocket.close(code=WS_CLOSE_INTERNAL)
        except Exception:
            pass


async def _authenticate(token: str, db) -> Optional[dict]:
    """Decode the access token and load the user.

    Returns None on any failure — the caller handles the close code.
    Mirrors `core.dependencies.get_current_user` but adapted for the WS
    code path (no FastAPI Depends, no HTTP exception). Each failure mode
    is logged so production issues are diagnosable from server logs.
    """
    try:
        payload = decode_token(token, token_type="access")
    except InvalidToken as exc:
        logger.info("Battle WS auth: token decode failed (%s)", exc)
        return None
    sub = payload.get("sub")
    if not sub:
        logger.info("Battle WS auth: token missing 'sub' claim")
        return None
    try:
        oid = ObjectId(sub)
    except Exception:
        logger.info("Battle WS auth: malformed user id %s in token", sub)
        return None
    user = await db["users"].find_one({"_id": oid}, {"hashed_password": 0})
    if user is None:
        logger.info("Battle WS auth: user %s not found in DB", sub)
        return None
    if not user.get("is_active", True):
        logger.info("Battle WS auth: user %s is inactive", sub)
        return None
    return user


async def _reject(websocket: WebSocket, code: int, message: str) -> None:
    """Send a final `error` message on the open WS, then close with `code`."""
    try:
        await websocket.send_json({"type": "error", "message": message})
    except Exception:
        pass
    try:
        await websocket.close(code=code)
    except Exception:
        pass
