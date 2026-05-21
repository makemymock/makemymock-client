"""Layer 3 — distribute N questions across selected topics.

Given a dict of {topic_id: priority_score} and a target N, decide how many
questions each topic gets. Algorithm: Hamilton's largest-remainder method.

  raw[t]  = (weight[t] / sum_weights) × N
  alloc[t] = floor(raw[t])
  remaining seats go to the topics with the largest fractional remainders

Two extras over textbook Hamilton:
  - Negative weights are clamped to 0.
  - If sum_weights == 0 (all topics tied with weight 0), split equally with
    the first `N mod K` topics each getting one extra.
  - "Min-1" rule: if a topic ended up with 0 *and* N ≥ K (enough seats to
    give everyone at least one), steal a seat from the largest allocation
    (provided that one has > 1).

Mirrors `distribute_questions_by_priority` in services_async.py:314.
"""

from __future__ import annotations

from engine.models import PriorityScore


def distribute_by_priority(
    priority_scores: dict[int, PriorityScore],
    total_questions: int,
) -> dict[int, int]:
    """Return {topic_id: question_count} summing to <= total_questions.

    Sums to exactly total_questions unless every weight is zero AND
    total_questions can't be evenly distributed AND `len == 0`; in all
    other paths the sum equals total_questions.
    """
    if not priority_scores:
        return {}

    weights = {tid: max(0.0, ps.score) for tid, ps in priority_scores.items()}

    if total_questions <= 0:
        return {tid: 0 for tid in weights}

    total_weight = sum(weights.values())

    # All-zero-weights fallback: equal split, remainder to first topics.
    if total_weight <= 0:
        k = len(weights)
        per = total_questions // k
        rem = total_questions % k
        out = {tid: per for tid in weights}
        for i, tid in enumerate(out):
            if i < rem:
                out[tid] += 1
        return out

    # Hamilton's method: floors + largest fractional remainders.
    raw = {tid: (w / total_weight) * total_questions for tid, w in weights.items()}
    out = {tid: int(r) for tid, r in raw.items()}
    allocated = sum(out.values())
    remaining = total_questions - allocated

    if remaining > 0:
        # Order topics by descending fractional remainder.
        by_frac = sorted(
            raw.items(),
            key=lambda kv: (kv[1] - int(kv[1])),
            reverse=True,
        )
        for i in range(remaining):
            tid = by_frac[i % len(by_frac)][0]
            out[tid] += 1

    # Min-1 rule: only if there are enough seats for everyone to get one.
    if total_questions >= len(out):
        for tid in list(out):
            if out[tid] == 0:
                # Steal from the topic that currently has the most.
                richest = max(out, key=out.get)
                if out[richest] > 1:
                    out[richest] -= 1
                    out[tid] = 1

    return out
