"""Layer 2 — topic priority score with time decay.

For each topic the user selected:
    priority = avg(score_contribution across attempts) × decay_factor

Where decay_factor is a step function on days-since-last-attempt:
    0..3   days ⇒ 1.0×  (no penalty)
    4..7   days ⇒ 1.2×
    8..14  days ⇒ 1.5×
    15..30 days ⇒ 2.0×
    31+    days ⇒ 2.5×  (likely forgotten)

Cold start: topics with zero attempts borrow the average of attempted
topics. If *every* selected topic is unattempted, a default of 5.0 is used.

Mirrors `get_topic_priority_scores` in services_async.py:244.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Iterable

from engine.config import (
    DECAY_THRESHOLD_RECENT, DECAY_THRESHOLD_WEEK, DECAY_THRESHOLD_TWO_WEEKS,
    DECAY_THRESHOLD_MONTH,
    DECAY_RECENT, DECAY_WEEK, DECAY_TWO_WEEKS, DECAY_MONTH, DECAY_FORGOTTEN,
    DEFAULT_COLD_START_PRIORITY,
    RECENCY_HALFLIFE_DAYS, RECENCY_BUCKET_DAYS,
)
from engine.models import Attempt, PriorityScore


def decay_factor(days_since_last: int | None) -> float:
    """Step-function decay multiplier."""
    if days_since_last is None or days_since_last <= DECAY_THRESHOLD_RECENT:
        return DECAY_RECENT
    if days_since_last <= DECAY_THRESHOLD_WEEK:
        return DECAY_WEEK
    if days_since_last <= DECAY_THRESHOLD_TWO_WEEKS:
        return DECAY_TWO_WEEKS
    if days_since_last <= DECAY_THRESHOLD_MONTH:
        return DECAY_MONTH
    return DECAY_FORGOTTEN


def _build_recency_buckets() -> tuple[float, ...]:
    """Precompute one weight per bucket using each bucket's midpoint.

    Returns () when recency weighting is disabled. Horizon is 4 half-lives
    (where weight ≈ 0.06); anything older clamps to the last bucket. The
    table is small (~12 entries at default 30-day buckets / 90-day
    half-life) and built once at module load.
    """
    if RECENCY_HALFLIFE_DAYS is None:
        return ()
    horizon_days = 4 * RECENCY_HALFLIFE_DAYS
    n = max(1, math.ceil(horizon_days / RECENCY_BUCKET_DAYS))
    half = RECENCY_BUCKET_DAYS / 2.0
    return tuple(
        0.5 ** ((i * RECENCY_BUCKET_DAYS + half) / RECENCY_HALFLIFE_DAYS)
        for i in range(n)
    )


_RECENCY_BUCKETS: tuple[float, ...] = _build_recency_buckets()


def _recency_weight(attempt: Attempt, now: datetime) -> float:
    """O(1) half-life weight via the precomputed bucket table.

    Returns 1.0 when recency weighting is disabled (RECENCY_HALFLIFE_DAYS=None).
    Future timestamps (clock skew) clamp to days_ago=0 ⇒ first-bucket weight.
    Ages beyond the table horizon clamp to the last bucket.
    """
    if not _RECENCY_BUCKETS:
        return 1.0
    days_ago = (now - attempt.attempted_at).days
    if days_ago < 0:
        days_ago = 0
    bucket = days_ago // RECENCY_BUCKET_DAYS
    if bucket >= len(_RECENCY_BUCKETS):
        bucket = len(_RECENCY_BUCKETS) - 1
    return _RECENCY_BUCKETS[bucket]


def _priority_for_one_topic(
    topic_id: int,
    attempts: list[Attempt],
    now: datetime,
) -> PriorityScore:
    """Priority for a single topic given its already-fetched attempts.

    base = recency-weighted mean of score_contribution
           (when RECENCY_HALFLIFE_DAYS is None, this collapses to a flat mean)
    decay = step function of (now - max(attempted_at)).days
    final = base × decay
    """
    if not attempts:
        return PriorityScore(
            topic_id=topic_id, score=0.0, base_score=0.0,
            decay_factor=1.0, attempt_count=0,
        )

    weights = [_recency_weight(a, now) for a in attempts]
    total_weight = sum(weights)
    if total_weight <= 0:
        # Pathological: all weights underflowed to zero. Fall back to flat mean.
        base = sum(a.score_contribution for a in attempts) / len(attempts)
    else:
        base = sum(a.score_contribution * w for a, w in zip(attempts, weights)) / total_weight

    last = max(a.attempted_at for a in attempts)
    days = (now - last).days
    decay = decay_factor(days)
    return PriorityScore(
        topic_id=topic_id,
        score=base * decay,
        base_score=base,
        decay_factor=decay,
        attempt_count=len(attempts),
    )


def priority_scores_for_topics(
    topic_ids: Iterable[int],
    attempts: list[Attempt],
    now: datetime,
    topic_chapters: dict[int, int] | None = None,
) -> dict[int, PriorityScore]:
    """Compute priority for every selected topic, with cold-start fallback.

    Behavior:
      1. Group attempts by topic.
      2. For each topic with attempts, compute base × decay
         (base is recency-weighted; see _priority_for_one_topic).
      3. For topics with zero attempts, borrow priority in this order:
           a. If `topic_chapters` is provided AND at least one *other selected
              topic in the same chapter* has attempts → use the average of
              that chapter's attempted topics in the selection.
           b. Else fall back to the average of all attempted selected topics.
           c. Else (no topics in the selection have attempts) →
              DEFAULT_COLD_START_PRIORITY.

      Note (a) only looks within the currently selected topic set — it does
      not reach into the wider catalogue. This avoids pulling unrelated
      historical data into the cold-start prior.
    """
    topic_ids = list(topic_ids)
    grouped: dict[int, list[Attempt]] = defaultdict(list)
    for a in attempts:
        if a.topic_id in topic_ids:
            grouped[a.topic_id].append(a)

    scores: dict[int, PriorityScore] = {}
    for tid in topic_ids:
        scores[tid] = _priority_for_one_topic(tid, grouped.get(tid, []), now)

    zero_count_topics = [tid for tid, s in scores.items() if s.attempt_count == 0]
    attempted_in_selection = {
        tid: s for tid, s in scores.items() if s.attempt_count > 0
    }

    if zero_count_topics and attempted_in_selection:
        # Pre-compute global fallback average (all attempted topics in the selection).
        global_avg = sum(s.score for s in attempted_in_selection.values()) / len(
            attempted_in_selection
        )

        for tid in zero_count_topics:
            borrowed = global_avg
            if topic_chapters is not None:
                target_chapter = topic_chapters.get(tid)
                if target_chapter is not None:
                    chapter_mate_scores = [
                        s.score
                        for other_tid, s in attempted_in_selection.items()
                        if topic_chapters.get(other_tid) == target_chapter
                    ]
                    if chapter_mate_scores:
                        borrowed = sum(chapter_mate_scores) / len(chapter_mate_scores)
            scores[tid] = PriorityScore(
                topic_id=tid, score=borrowed, base_score=borrowed,
                decay_factor=1.0, attempt_count=0,
            )
    elif zero_count_topics and not attempted_in_selection:
        for tid in zero_count_topics:
            scores[tid] = PriorityScore(
                topic_id=tid, score=DEFAULT_COLD_START_PRIORITY,
                base_score=DEFAULT_COLD_START_PRIORITY,
                decay_factor=1.0, attempt_count=0,
            )

    return scores
