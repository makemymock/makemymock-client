"""Battle orchestration — runs the live game loop for a paired battle.

This module is the only place where the WebSockets of both players are
driven simultaneously. After the matchmaker spawns `run_battle_loop` as a
background task, both player handlers just sit on `battle.completion_event`
to keep their connections open. We send every message, receive every
answer, grade server-side, and persist the result.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import WebSocket
from motor.motor_asyncio import AsyncIOMotorDatabase
from starlette.websockets import WebSocketDisconnect, WebSocketState

from modules.battle.constants import (
    BASE_POINTS_CORRECT,
    COUNTDOWN_GO_PAUSE_SECONDS,
    COUNTDOWN_SECONDS,
    QUESTIONS_PER_BATTLE,
    REVEAL_PAUSE_SECONDS,
    SECONDS_PER_QUESTION,
    SPEED_BONUS_MAX,
)
from modules.battle.matchmaker import Battle, BattleMatchmaker, Player
from modules.battle.matchmaker.keys import (
    BATTLE_SESSION_TTL,
    battle_round_answers,
    player_inbox,
)
from modules.battle.model import new_battle_doc
from modules.battle.repository import BattleRepository

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

async def run_battle_loop(
    battle: Battle,
    db: AsyncIOMotorDatabase,
    manager: BattleMatchmaker,
    *,
    redis: Optional[object] = None,
) -> None:
    """Drive an entire battle from match → completion → persistence.

    Routes to local in-process loop if both players are on this container,
    or distributed loop if players are on separate containers.
    """
    if getattr(battle, "is_distributed", False):
        await _run_distributed_battle_loop(battle, db, manager, redis)
        return

    repo = BattleRepository(db)
    started_at_wall = datetime.now(timezone.utc)
    battle.started_at = time.monotonic()

    try:
        # 1) Fetch questions if not already attached.
        if not battle.questions:
            questions = await repo.sample_random_questions(QUESTIONS_PER_BATTLE)
            if len(questions) < QUESTIONS_PER_BATTLE:
                await _send_both(battle, {
                    "type": "error",
                    "message": "Could not source enough questions for a battle.",
                })
                return
            battle.questions = questions
        else:
            questions = battle.questions

        # 2) Announce the match to both players.
        await _send_both(battle, {
            "type": "matched",
            "battle_id": battle.battle_id,
            "questions_count": len(questions),
            "time_per_question": SECONDS_PER_QUESTION,
            "opponent_for_a": {"username": battle.player_b.username},
            "opponent_for_b": {"username": battle.player_a.username},
        }, route_per_player=True)

        # 3) Countdown — `5, 4, 3, 2, 1, GO!`
        for n in range(COUNTDOWN_SECONDS, 0, -1):
            await _send_both(battle, {"type": "countdown", "value": n})
            await asyncio.sleep(1.0)
        await _send_both(battle, {"type": "countdown", "value": 0})
        await asyncio.sleep(COUNTDOWN_GO_PAUSE_SECONDS)

        # 4) Question rounds.
        rounds: list[dict] = []
        for idx, q in enumerate(questions):
            round_doc = await _run_round(battle, idx, q)
            rounds.append(round_doc)
            if battle.player_a.disconnected or battle.player_b.disconnected:
                break
            # Reveal pause (skip after the last round).
            if idx < len(questions) - 1:
                await asyncio.sleep(REVEAL_PAUSE_SECONDS)

        # 5) Decide winner + send final.
        winner_key = _determine_winner(battle)
        await _send_complete(battle, winner_key, rounds)

        # 6) Persist.
        await _persist_battle(repo, battle, rounds, started_at_wall, winner_key)

    except Exception:
        logger.exception("Battle %s crashed; closing both sockets", battle.battle_id)
        try:
            await _send_both(battle, {
                "type": "error",
                "message": "The battle ran into an unexpected error.",
            })
        except Exception:
            pass
    finally:
        await manager.release_slot(str(battle.player_a.user_id))
        await manager.release_slot(str(battle.player_b.user_id))
        battle.completion_event.set()
        # Give a beat for the final message to flush, then close.
        await asyncio.sleep(0.2)
        await _close_ws(battle.player_a.ws)
        await _close_ws(battle.player_b.ws)


# ---------------------------------------------------------------------------
# Distributed game loop (Cross-Container Coordination)
# ---------------------------------------------------------------------------

async def _run_distributed_battle_loop(
    battle: Battle,
    db: AsyncIOMotorDatabase,
    manager: BattleMatchmaker,
    redis: Optional[object],
) -> None:
    repo = BattleRepository(db)
    started_at_wall = datetime.now(timezone.utc)
    battle.started_at = time.monotonic()

    local_player = battle.player_a if battle.local_role == "a" else battle.player_b
    remote_player = battle.player_b if battle.local_role == "a" else battle.player_a
    local_role = battle.local_role
    remote_role = "b" if local_role == "a" else "a"
    local_uid = str(local_player.user_id)
    remote_uid = str(remote_player.user_id)

    try:
        # 1. Announce match to local player
        await _safe_send(local_player.ws, {
            "type": "matched",
            "battle_id": battle.battle_id,
            "questions_count": len(battle.questions),
            "time_per_question": SECONDS_PER_QUESTION,
            "opponent": {"username": remote_player.username},
        })

        # 2. Synchronized countdown (5..0)
        for n in range(COUNTDOWN_SECONDS, 0, -1):
            await _safe_send(local_player.ws, {"type": "countdown", "value": n})
            await asyncio.sleep(1.0)
        await _safe_send(local_player.ws, {"type": "countdown", "value": 0})
        await asyncio.sleep(COUNTDOWN_GO_PAUSE_SECONDS)

        # 3. Question rounds
        rounds: list[dict] = []
        for idx, q_doc in enumerate(battle.questions):
            round_doc = await _run_distributed_round(
                battle, idx, q_doc, local_player, remote_player, local_role, remote_role, local_uid, remote_uid, redis,
            )
            rounds.append(round_doc)
            if local_player.disconnected or remote_player.disconnected:
                break
            if idx < len(battle.questions) - 1:
                await asyncio.sleep(REVEAL_PAUSE_SECONDS)

        # 4. Determine winner & send completion
        winner_key = _determine_winner(battle)
        result_for_local = (
            "win" if winner_key == local_role else "loss" if winner_key == remote_role else "draw"
        )
        await _safe_send(local_player.ws, {
            "type": "battle_complete",
            "battle_id": battle.battle_id,
            "rounds_played": len(rounds),
            "result": result_for_local,
            "your_score": local_player.score,
            "your_correct": local_player.correct_count,
            "opponent_score": remote_player.score,
            "opponent_correct": remote_player.correct_count,
            "opponent_username": remote_player.username,
        })

        # 5. Persist to MongoDB (Only Coordinator persists to avoid duplicate writes)
        if battle.is_coordinator:
            await _persist_battle(repo, battle, rounds, started_at_wall, winner_key)

    except Exception:
        logger.exception("Distributed battle %s error for role %s", battle.battle_id, local_role)
        try:
            await _safe_send(local_player.ws, {
                "type": "error",
                "message": "The battle ran into an unexpected error.",
            })
        except Exception:
            pass
    finally:
        await manager.release_slot(local_uid)
        battle.completion_event.set()
        await asyncio.sleep(0.2)
        await _close_ws(local_player.ws)


async def _run_distributed_round(
    battle: Battle,
    idx: int,
    q_doc: dict,
    local_player: Player,
    remote_player: Player,
    local_role: str,
    remote_role: str,
    local_uid: str,
    remote_uid: str,
    redis: Optional[object],
) -> dict:
    total = len(battle.questions)
    options = _public_options(q_doc)
    correct_key = _correct_option_of(q_doc)
    question_text = q_doc.get("questionText", "")
    question_image = q_doc.get("questionImg") or None
    difficulty = (q_doc.get("difficulty") or "medium").lower()
    qid = str(q_doc["_id"])
    ans_key = battle_round_answers(battle.battle_id, idx)
    inbox_key = player_inbox(local_uid)

    payload = {
        "type": "question",
        "index": idx,
        "total": total,
        "question_id": qid,
        "question_text": question_text,
        "question_image": question_image,
        "options": options,
        "difficulty": difficulty,
        "time_limit_seconds": SECONDS_PER_QUESTION,
    }
    await _safe_send(local_player.ws, payload)
    sent_at = time.monotonic()
    deadline = sent_at + SECONDS_PER_QUESTION

    local_ans: Optional[dict] = None
    remote_ans: Optional[dict] = None

    async def collect_local():
        nonlocal local_ans
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                msg = await asyncio.wait_for(
                    local_player.ws.receive_json(),
                    timeout=max(0.05, remaining),
                )
            except asyncio.TimeoutError:
                return
            except WebSocketDisconnect:
                local_player.disconnected = True
                if redis is not None:
                    await redis.lpush(player_inbox(remote_uid), json.dumps({"type": "player_disconnected", "role": local_role}))
                return
            except Exception:
                if getattr(local_player.ws, "client_state", None) == WebSocketState.DISCONNECTED or getattr(local_player.ws, "application_state", None) == WebSocketState.DISCONNECTED:
                    local_player.disconnected = True
                    return
                continue
            if msg.get("type") != "submit_answer" or str(msg.get("question_id")) != qid:
                continue
            response_time = time.monotonic() - sent_at
            local_ans = {
                "selected_option": str(msg.get("selected_option") or ""),
                "response_time": response_time,
            }
            if redis is not None:
                await redis.hset(ans_key, values={local_role: json.dumps(local_ans)})
                await redis.expire(ans_key, BATTLE_SESSION_TTL)
                await redis.lpush(player_inbox(remote_uid), json.dumps({"type": "opponent_answered", "question_id": qid}))
            return

    async def monitor_remote():
        nonlocal remote_ans
        while time.monotonic() < deadline:
            if redis is None:
                break
            try:
                raw = await redis.rpop(inbox_key)
                if raw:
                    data = json.loads(raw) if isinstance(raw, str) else raw
                    if data.get("type") == "opponent_answered":
                        await _safe_send(local_player.ws, {"type": "opponent_answered", "question_id": qid})
                    elif data.get("type") == "player_disconnected":
                        remote_player.disconnected = True
                        return

                if remote_ans is None:
                    stored = await redis.hget(ans_key, remote_role)
                    if stored:
                        remote_ans = json.loads(stored) if isinstance(stored, str) else stored

                if remote_ans is not None and local_ans is not None:
                    return
            except Exception as exc:
                logger.debug("Error monitoring remote answer: %s", exc)
            await asyncio.sleep(0.08)

    await asyncio.gather(collect_local(), monitor_remote())

    if redis is not None and remote_ans is None:
        try:
            stored = await redis.hget(ans_key, remote_role)
            if stored:
                remote_ans = json.loads(stored) if isinstance(stored, str) else stored
        except Exception:
            pass

    a_ans = local_ans if local_role == "a" else remote_ans
    b_ans = local_ans if local_role == "b" else remote_ans

    a_correct = bool(a_ans and a_ans.get("selected_option") == correct_key)
    b_correct = bool(b_ans and b_ans.get("selected_option") == correct_key)
    a_delta = _score_for(a_correct, (a_ans or {}).get("response_time"))
    b_delta = _score_for(b_correct, (b_ans or {}).get("response_time"))

    battle.player_a.score += a_delta
    battle.player_b.score += b_delta
    if a_correct:
        battle.player_a.correct_count += 1
    if b_correct:
        battle.player_b.correct_count += 1

    your_ans = a_ans if local_role == "a" else b_ans
    your_correct = a_correct if local_role == "a" else b_correct
    your_delta = a_delta if local_role == "a" else b_delta
    your_total = battle.player_a.score if local_role == "a" else battle.player_b.score

    opp_ans = b_ans if local_role == "a" else a_ans
    opp_correct = b_correct if local_role == "a" else a_correct
    opp_delta = b_delta if local_role == "a" else a_delta
    opp_total = battle.player_b.score if local_role == "a" else battle.player_a.score

    await _safe_send(local_player.ws, {
        "type": "question_result",
        "question_id": qid,
        "correct_option": correct_key,
        "your_answer": (your_ans or {}).get("selected_option"),
        "your_correct": your_correct,
        "your_score_delta": your_delta,
        "your_total_score": your_total,
        "opponent_answer": (opp_ans or {}).get("selected_option"),
        "opponent_correct": opp_correct,
        "opponent_score_delta": opp_delta,
        "opponent_total_score": opp_total,
    })

    round_doc = {
        "index": idx,
        "question_id": qid,
        "question_text": question_text,
        "options": options,
        "correct_option": correct_key,
        "player_a": {
            "answer": (a_ans or {}).get("selected_option"),
            "correct": a_correct,
            "response_time": (a_ans or {}).get("response_time"),
            "score_delta": a_delta,
        },
        "player_b": {
            "answer": (b_ans or {}).get("selected_option"),
            "correct": b_correct,
            "response_time": (b_ans or {}).get("response_time"),
            "score_delta": b_delta,
        },
    }
    battle.player_a.answers.append(round_doc["player_a"])
    battle.player_b.answers.append(round_doc["player_b"])
    return round_doc


# ---------------------------------------------------------------------------
# Round loop
# ---------------------------------------------------------------------------

async def _run_round(battle: Battle, idx: int, q_doc: dict) -> dict:
    """Run a single question round, return the per-round result doc."""
    total = len(battle.questions)
    options = _public_options(q_doc)
    correct_key = _correct_option_of(q_doc)
    question_text = q_doc.get("questionText", "")
    question_image = q_doc.get("questionImg") or None
    difficulty = (q_doc.get("difficulty") or "medium").lower()
    qid = str(q_doc["_id"])

    payload = {
        "type": "question",
        "index": idx,
        "total": total,
        "question_id": qid,
        "question_text": question_text,
        "question_image": question_image,
        "options": options,
        "difficulty": difficulty,
        "time_limit_seconds": SECONDS_PER_QUESTION,
    }
    await _send_both(battle, payload)
    sent_at = time.monotonic()

    # Collect answers concurrently — both players have the full per-question
    # timer to submit, with faster correct answers earning a higher speed bonus.
    answers: dict[str, dict] = {}

    async def collect(player_key: str, player: Player):
        deadline = sent_at + SECONDS_PER_QUESTION
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                msg = await asyncio.wait_for(
                    player.ws.receive_json(),
                    timeout=max(0.05, remaining),
                )
            except asyncio.TimeoutError:
                return
            except WebSocketDisconnect:
                player.disconnected = True
                return
            except (ValueError, TypeError) as exc:
                # Malformed JSON or non-dict payload — ignore frame without forfeiting match
                logger.warning("Ignored unparseable WS payload from %s: %s", player.username, exc)
                continue
            except Exception as exc:
                # Only mark disconnected if the WebSocket is actually closed/terminated
                if getattr(player.ws, "client_state", None) == WebSocketState.DISCONNECTED or getattr(player.ws, "application_state", None) == WebSocketState.DISCONNECTED:
                    player.disconnected = True
                    return
                logger.warning("Unexpected error receiving WS frame from %s: %s", player.username, exc)
                continue
            if msg.get("type") != "submit_answer":
                continue
            if str(msg.get("question_id")) != qid:
                continue  # stale answer for a previous question — ignore
            response_time = time.monotonic() - sent_at
            answers[player_key] = {
                "selected_option": str(msg.get("selected_option") or ""),
                "response_time": response_time,
            }
            # Tell the OPPONENT this player has locked in.
            opp = battle.player_b if player_key == "a" else battle.player_a
            await _safe_send(opp.ws, {
                "type": "opponent_answered",
                "question_id": qid,
            })
            return

    await asyncio.gather(
        collect("a", battle.player_a),
        collect("b", battle.player_b),
    )

    # Grade + score.
    a_ans = answers.get("a")
    b_ans = answers.get("b")
    a_correct = bool(a_ans and a_ans["selected_option"] == correct_key)
    b_correct = bool(b_ans and b_ans["selected_option"] == correct_key)
    a_delta = _score_for(a_correct, (a_ans or {}).get("response_time"))
    b_delta = _score_for(b_correct, (b_ans or {}).get("response_time"))

    battle.player_a.score += a_delta
    battle.player_b.score += b_delta
    if a_correct:
        battle.player_a.correct_count += 1
    if b_correct:
        battle.player_b.correct_count += 1

    # Per-player reveal with their own perspective (you/opponent).
    await _safe_send(battle.player_a.ws, {
        "type": "question_result",
        "question_id": qid,
        "correct_option": correct_key,
        "your_answer": (a_ans or {}).get("selected_option"),
        "your_correct": a_correct,
        "your_score_delta": a_delta,
        "your_total_score": battle.player_a.score,
        "opponent_answer": (b_ans or {}).get("selected_option"),
        "opponent_correct": b_correct,
        "opponent_score_delta": b_delta,
        "opponent_total_score": battle.player_b.score,
    })
    await _safe_send(battle.player_b.ws, {
        "type": "question_result",
        "question_id": qid,
        "correct_option": correct_key,
        "your_answer": (b_ans or {}).get("selected_option"),
        "your_correct": b_correct,
        "your_score_delta": b_delta,
        "your_total_score": battle.player_b.score,
        "opponent_answer": (a_ans or {}).get("selected_option"),
        "opponent_correct": a_correct,
        "opponent_score_delta": a_delta,
        "opponent_total_score": battle.player_a.score,
    })

    round_doc = {
        "index": idx,
        "question_id": qid,
        "question_text": question_text,
        "options": options,
        "correct_option": correct_key,
        "player_a": {
            "answer": (a_ans or {}).get("selected_option"),
            "correct": a_correct,
            "response_time": (a_ans or {}).get("response_time"),
            "score_delta": a_delta,
        },
        "player_b": {
            "answer": (b_ans or {}).get("selected_option"),
            "correct": b_correct,
            "response_time": (b_ans or {}).get("response_time"),
            "score_delta": b_delta,
        },
    }
    battle.player_a.answers.append(round_doc["player_a"])
    battle.player_b.answers.append(round_doc["player_b"])
    return round_doc


# ---------------------------------------------------------------------------
# Scoring + winner
# ---------------------------------------------------------------------------

def _score_for(is_correct: bool, response_time: Optional[float]) -> int:
    """Base points for a correct answer + a linear speed bonus.

    The faster you answer (relative to the question timer), the bigger the
    bonus. Slowest correct answers still get full base points so the game
    rewards accuracy first, speed second.
    """
    if not is_correct:
        return 0
    if response_time is None:
        return BASE_POINTS_CORRECT
    t = max(0.0, min(response_time, SECONDS_PER_QUESTION))
    speed_ratio = 1.0 - (t / SECONDS_PER_QUESTION)
    bonus = int(round(SPEED_BONUS_MAX * speed_ratio))
    return BASE_POINTS_CORRECT + bonus


def _determine_winner(battle: Battle) -> str:
    """Return 'a', 'b', or 'draw'."""
    a, b = battle.player_a, battle.player_b
    # Disconnect = automatic loss.
    if a.disconnected and not b.disconnected:
        return "b"
    if b.disconnected and not a.disconnected:
        return "a"
    if a.score > b.score:
        return "a"
    if b.score > a.score:
        return "b"
    # Tiebreaker — more correct answers wins.
    if a.correct_count > b.correct_count:
        return "a"
    if b.correct_count > a.correct_count:
        return "b"
    return "draw"


# ---------------------------------------------------------------------------
# WebSocket helpers
# ---------------------------------------------------------------------------

async def _send_complete(battle: Battle, winner_key: str, rounds: list[dict]) -> None:
    a, b = battle.player_a, battle.player_b
    result_for_a = (
        "win" if winner_key == "a" else "loss" if winner_key == "b" else "draw"
    )
    result_for_b = (
        "win" if winner_key == "b" else "loss" if winner_key == "a" else "draw"
    )
    base = {
        "type": "battle_complete",
        "battle_id": battle.battle_id,
        "rounds_played": len(rounds),
    }
    await _safe_send(a.ws, {
        **base,
        "result": result_for_a,
        "your_score": a.score,
        "your_correct": a.correct_count,
        "opponent_score": b.score,
        "opponent_correct": b.correct_count,
        "opponent_username": b.username,
    })
    await _safe_send(b.ws, {
        **base,
        "result": result_for_b,
        "your_score": b.score,
        "your_correct": b.correct_count,
        "opponent_score": a.score,
        "opponent_correct": a.correct_count,
        "opponent_username": a.username,
    })


async def _send_both(
    battle: Battle, msg: dict, *, route_per_player: bool = False,
) -> None:
    """Send the same payload to both players.

    When `route_per_player=True`, the payload may contain `opponent_for_a`
    and `opponent_for_b` keys; this helper unpacks the right one into
    `opponent` for each side and drops the routing keys.
    """
    if not route_per_player:
        await asyncio.gather(
            _safe_send(battle.player_a.ws, msg),
            _safe_send(battle.player_b.ws, msg),
        )
        return

    msg_a = {k: v for k, v in msg.items() if k not in ("opponent_for_a", "opponent_for_b")}
    msg_b = dict(msg_a)
    if "opponent_for_a" in msg:
        msg_a["opponent"] = msg["opponent_for_a"]
    if "opponent_for_b" in msg:
        msg_b["opponent"] = msg["opponent_for_b"]
    await asyncio.gather(
        _safe_send(battle.player_a.ws, msg_a),
        _safe_send(battle.player_b.ws, msg_b),
    )


async def _safe_send(ws: Optional[WebSocket], msg: dict) -> bool:
    if ws is None:
        return False
    try:
        if getattr(ws, "application_state", None) == WebSocketState.DISCONNECTED or getattr(ws, "client_state", None) == WebSocketState.DISCONNECTED:
            return False
        await ws.send_json(msg)
        return True
    except Exception:
        return False


async def _close_ws(ws: Optional[WebSocket]) -> None:
    if ws is None:
        return
    try:
        if getattr(ws, "application_state", None) != WebSocketState.DISCONNECTED:
            await ws.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Catalog → public option projection
# ---------------------------------------------------------------------------

def _public_options(doc: dict) -> list[dict]:
    out: list[dict] = []
    for key in ("A", "B", "C", "D"):
        text = doc.get(f"option{key}")
        if text is None or str(text).strip() == "":
            continue
        out.append({"key": key, "text": str(text)})
    return out


def _correct_option_of(doc: dict) -> str:
    co = doc.get("correctOption")
    if co:
        return str(co).strip().upper()
    cos = doc.get("correctOptions") or []
    if cos:
        return str(cos[0]).strip().upper()
    return ""


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

async def _persist_battle(
    repo: BattleRepository,
    battle: Battle,
    rounds: list[dict],
    started_at: datetime,
    winner_key: str,
) -> None:
    a, b = battle.player_a, battle.player_b
    winner_uid = (
        a.user_id if winner_key == "a"
        else b.user_id if winner_key == "b"
        else None
    )
    # Trim each round to a replay-friendly shape.
    rounds_snapshot = [
        {
            "index": r["index"],
            "question_id": r["question_id"],
            "question_text": r["question_text"],
            "options": r["options"],
            "correct_option": r["correct_option"],
            "player_a_answer": r["player_a"]["answer"],
            "player_a_correct": r["player_a"]["correct"],
            "player_a_score_delta": r["player_a"]["score_delta"],
            "player_b_answer": r["player_b"]["answer"],
            "player_b_correct": r["player_b"]["correct"],
            "player_b_score_delta": r["player_b"]["score_delta"],
        }
        for r in rounds
    ]
    questions_snapshot = [
        {
            "question_id": r["question_id"],
            "question_text": r["question_text"],
            "options": r["options"],
            "correct_option": r["correct_option"],
        }
        for r in rounds
    ]
    doc = new_battle_doc(
        battle_id=battle.battle_id,
        player_a_user_id=a.user_id,
        player_a_username=a.username,
        player_b_user_id=b.user_id,
        player_b_username=b.username,
        questions=questions_snapshot,
        rounds=rounds_snapshot,
        player_a_score=a.score,
        player_b_score=b.score,
        player_a_correct=a.correct_count,
        player_b_correct=b.correct_count,
        winner_user_id=winner_uid,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
    )
    try:
        await repo.insert_battle(doc)
    except Exception:
        logger.exception("Failed to persist battle %s", battle.battle_id)
