"""Redis-backed caching for the contest module.

Provides three optimizations over pure-MongoDB:

1. **Live leaderboard** — Sorted Set for O(log N) rank lookups
   (replaces the O(N) ``count_ranked_above`` MongoDB scan).
2. **Submission deduplication** — SETNX guard to prevent the
   double-submit race more cheaply than MongoDB ``submitted_at`` check.
3. **Participant counter** — INCR for live participant counts without
   hitting MongoDB ``count_documents`` on every lobby page load.

All operations degrade gracefully: if Redis is unavailable or a
command fails, the caller falls back to MongoDB (which remains the
source of truth).
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# TTLs (seconds)
LEADERBOARD_TTL = 86_400     # 24 h
PARTICIPANT_TTL = 86_400     # 24 h
SUBMISSION_LOCK_TTL = 14_400  # 4 h


# ── Key builders ─────────────────────────────────────────────────────

def _lb_key(contest_id: str) -> str:
    return f"contest:lb:{contest_id}"

def _participants_key(contest_id: str) -> str:
    return f"contest:participants:{contest_id}"

def _submitted_key(contest_id: str, user_id: str) -> str:
    return f"contest:submitted:{contest_id}:{user_id}"


# ── Leaderboard ──────────────────────────────────────────────────────

def _composite_score(score: float, time_taken_seconds: int) -> float:
    """Encode (score, time) into a single float for the sorted set.

    Higher score is better; among equal scores, lower time is better.
    Encoding: ``score * 1_000_000 - time_taken_seconds``.

    This puts higher-scoring users at a higher ZADD score, and among
    ties, the one with less time gets a higher composite score.
    """
    return score * 1_000_000 - time_taken_seconds


async def leaderboard_add(
    redis, contest_id: str, user_id: str,
    score: float, time_taken_seconds: int,
) -> None:
    """Add or update a user's leaderboard entry after submission."""
    if redis is None:
        return
    try:
        key = _lb_key(contest_id)
        composite = _composite_score(score, time_taken_seconds)
        await redis.zadd(key, {user_id: composite})
        await redis.expire(key, LEADERBOARD_TTL)
    except Exception:
        logger.exception("Redis leaderboard_add failed for contest=%s", contest_id)


async def leaderboard_rank(
    redis, contest_id: str, user_id: str,
) -> Optional[int]:
    """Return the 1-based rank for a user, or None if not in the set.

    Uses ZREVRANK (O(log N)) instead of the MongoDB count query.
    """
    if redis is None:
        return None
    try:
        rank = await redis.zrevrank(_lb_key(contest_id), user_id)
        if rank is not None:
            return rank + 1  # ZREVRANK is 0-based
        return None
    except Exception:
        logger.exception("Redis leaderboard_rank failed for contest=%s", contest_id)
        return None


async def leaderboard_total(
    redis, contest_id: str,
) -> Optional[int]:
    """Return total participants in the sorted set, or None."""
    if redis is None:
        return None
    try:
        return await redis.zcard(_lb_key(contest_id))
    except Exception:
        logger.exception("Redis leaderboard_total failed")
        return None


async def leaderboard_top(
    redis, contest_id: str, limit: int,
) -> Optional[list[dict]]:
    """Return top-K entries as [{user_id, composite_score}, ...].

    Returns None on failure so the caller can fall back to MongoDB.
    """
    if redis is None:
        return None
    try:
        # ZREVRANGE with scores returns [(member, score), ...]
        results = await redis.zrange(
            _lb_key(contest_id), 0, limit - 1,
            withscores=True, rev=True,
        )
        if results is None:
            return None
        out = []
        for item in results:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                out.append({"user_id": item[0], "composite_score": item[1]})
            else:
                # Upstash may return differently; handle gracefully
                out.append({"user_id": str(item), "composite_score": 0})
        return out
    except Exception:
        logger.exception("Redis leaderboard_top failed for contest=%s", contest_id)
        return None


# ── Submission deduplication ─────────────────────────────────────────

async def try_claim_submission(
    redis, contest_id: str, user_id: str,
) -> Optional[bool]:
    """Attempt to claim a one-time submission lock.

    Returns True if claimed (first submit), False if already submitted,
    None on Redis failure (caller should fall back to MongoDB check).
    """
    if redis is None:
        return None
    try:
        result = await redis.set(
            _submitted_key(contest_id, user_id), "1",
            nx=True, ex=SUBMISSION_LOCK_TTL,
        )
        return bool(result)
    except Exception:
        logger.exception("Redis try_claim_submission failed")
        return None


# ── Participant counter ──────────────────────────────────────────────

async def increment_participants(
    redis, contest_id: str,
) -> Optional[int]:
    """Increment the participant counter. Returns the new count."""
    if redis is None:
        return None
    try:
        key = _participants_key(contest_id)
        count = await redis.incr(key)
        await redis.expire(key, PARTICIPANT_TTL)
        return count
    except Exception:
        logger.exception("Redis increment_participants failed")
        return None
