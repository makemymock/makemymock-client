"""Layer 4 — adaptive difficulty mix per topic.

Given the user's recent attempts in a topic, decide what difficulty mix the
next batch of questions should have. There is a 5-stage ladder:

    Stage 1: Easy only                   → {'easy': 1.0}
    Stage 2: Easy + Medium mix           → {'easy': 0.4, 'medium': 0.6}
    Stage 3: Medium only                 → {'medium': 1.0}
    Stage 4: Medium + Hard mix           → {'medium': 0.4, 'hard': 0.6}
    Stage 5: Hard only                   → {'hard': 1.0}

The current stage is *inferred* from the difficulty composition of the
user's last 15 attempts. Promotion/demotion is then a function of accuracy
within those attempts.

Mirrors `calculate_progression_mix` in services_async.py:65, with one
intentional divergence: the stage-detection threshold comparisons use
`>=` instead of `>`.

Why the divergence: production uses strict `>` against 0.3 and 0.6.
With production's 15-attempt window, integer counts can never produce
*exactly* 0.3, so the bug doesn't fire in steady state. But for users
with fewer than 15 attempts in a topic (early-stage users — the case
where stage detection matters most), a spread like 3 easy / 3 medium /
4 hard in a 10-attempt window produces pct_easy = pct_medium = 0.3,
all `>` checks fail, and the classifier falls through to "Stage 1 →
easy only" — even though 40% of the user's recent practice was on
hard problems.

The `>=` partition is *complete*: every (pct_easy, pct_medium, pct_hard)
triple maps to exactly one stage.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from engine.config import (
    PROGRESSION_WINDOW_SIZE, MIN_ATTEMPTS_FOR_PROG,
    ACC_PROMOTE_EASY_TO_MIX, ACC_PROMOTE_MIX_TO_MED,
    ACC_PROMOTE_MED_TO_MIX_MH, ACC_PROMOTE_MIX_MH_TO_HARD,
    ACC_DEMOTE_TO_EASY, ACC_DEMOTE_TO_MIX_EM,
    ACC_DEMOTE_TO_MED, ACC_DEMOTE_TO_MIX_MH,
)
from engine.models import Attempt


def progression_mix(attempts: Iterable[Attempt]) -> dict[str, float]:
    """Return the difficulty-mix weights for the next batch.

    Output keys are a subset of {'easy', 'medium', 'hard'}, with values
    that sum to 1.0.
    """
    items = list(attempts)
    if not items:
        return {"easy": 1.0}

    # Sort by time (most recent first), keep the window.
    items.sort(key=lambda a: a.attempted_at, reverse=True)
    window = items[:PROGRESSION_WINDOW_SIZE]

    if len(window) < MIN_ATTEMPTS_FOR_PROG:
        # Insufficient data → infer from the most recent attempt only.
        last_diff = window[0].difficulty.lower()
        if last_diff == "hard":
            return {"medium": 0.3, "hard": 0.7}
        if last_diff == "medium":
            return {"easy": 0.3, "medium": 0.7}
        return {"easy": 1.0}

    # Composition of the window. `corrects` accumulates fractional credit
    # (1.0 for binary-correct, 0.0 for binary-wrong, anything in between
    # for partial-credit attempts on multi_correct / matching). Mean
    # correctness per difficulty then drives the stage thresholds.
    counts = {"easy": 0, "medium": 0, "hard": 0}
    corrects: dict[str, float] = {"easy": 0.0, "medium": 0.0, "hard": 0.0}
    for a in window:
        d = a.difficulty.lower()
        if d in counts:
            counts[d] += 1
            corrects[d] += a.effective_correctness

    total = len(window)
    pct_easy = counts["easy"] / total
    pct_medium = counts["medium"] / total
    pct_hard = counts["hard"] / total

    acc_easy = corrects["easy"] / counts["easy"] if counts["easy"] else 0.0
    acc_medium = corrects["medium"] / counts["medium"] if counts["medium"] else 0.0
    acc_hard = corrects["hard"] / counts["hard"] if counts["hard"] else 0.0

    # ---- Stage 5: Mostly Hard (≥60% of window) ----
    if pct_hard >= 0.6:
        if acc_hard < ACC_DEMOTE_TO_MIX_MH:
            return {"medium": 0.4, "hard": 0.6}     # demote to Mix(M+H)
        return {"hard": 1.0}                         # stay

    # ---- Stage 4: Mix Medium/Hard (≥30% each) ----
    if pct_medium >= 0.3 and pct_hard >= 0.3:
        if acc_hard > ACC_PROMOTE_MIX_MH_TO_HARD:
            return {"hard": 1.0}                     # promote
        if acc_medium < ACC_DEMOTE_TO_MED:
            return {"medium": 1.0}                   # demote to Medium
        return {"medium": 0.4, "hard": 0.6}          # stay

    # ---- Stage 3: Mostly Medium (≥60%) ----
    if pct_medium >= 0.6:
        if acc_medium > ACC_PROMOTE_MED_TO_MIX_MH:
            return {"medium": 0.4, "hard": 0.6}      # promote to Mix(M+H)
        if acc_medium < ACC_DEMOTE_TO_MIX_EM:
            return {"easy": 0.4, "medium": 0.6}      # demote to Mix(E+M)
        return {"medium": 1.0}                       # stay

    # ---- Stage 2: Mix Easy/Medium (≥30% each) ----
    if pct_easy >= 0.3 and pct_medium >= 0.3:
        if acc_medium > ACC_PROMOTE_MIX_TO_MED:
            return {"medium": 1.0}                   # promote
        if acc_easy < ACC_DEMOTE_TO_EASY:
            return {"easy": 1.0}                     # demote to Easy
        return {"easy": 0.4, "medium": 0.6}          # stay

    # ---- Stage 1: Else (mostly easy — pct_easy >= 0.7 given the partition) ----
    if acc_easy > ACC_PROMOTE_EASY_TO_MIX:
        return {"easy": 0.4, "medium": 0.6}          # promote to Mix(E+M)
    return {"easy": 1.0}                             # stay
