"""Layer 1 — per-attempt scoring.

Maps (is_correct, difficulty) → a single score contribution. Higher score
means "this attempt suggests the user needs more practice in this topic".

Mirrors `get_score_contribution` in
phase/Phase-backend/app/services/mock_test/services_async.py:40.
"""

from __future__ import annotations

from engine.config import (
    CORRECT_EASY, CORRECT_MEDIUM, CORRECT_HARD,
    INCORRECT_EASY, INCORRECT_MEDIUM, INCORRECT_HARD,
)


def score_contribution(is_correct: bool, difficulty: str) -> int:
    """Return the score contribution for a single binary attempt.

    Matches the original behavior:
    - difficulty matching is case-insensitive
    - unknown difficulty falls through to the 'hard' branch (this mirrors
      the original `else: # hard` fallback at services_async.py:53)

    For partial credit, use `score_contribution_partial` instead.
    """
    return score_contribution_partial(1.0 if is_correct else 0.0, difficulty)


def score_contribution_partial(correctness: float, difficulty: str) -> int:
    """Return the score contribution for a fractionally-correct attempt.

    `correctness` ∈ [0, 1]:
      1.0 → CORRECT_<difficulty>      (low score; topic doesn't need practice)
      0.0 → INCORRECT_<difficulty>    (high score; topic needs practice)
      0.5 → midpoint between the two
    Out-of-range values are clamped.

    Only multi_correct and matching question types ever pass a non-binary
    correctness; the others always pass 0.0 or 1.0 and behave identically
    to `score_contribution`.
    """
    c = max(0.0, min(1.0, correctness))
    d = (difficulty or "").lower()

    if d == "easy":
        full_right, full_wrong = CORRECT_EASY, INCORRECT_EASY
    elif d == "medium":
        full_right, full_wrong = CORRECT_MEDIUM, INCORRECT_MEDIUM
    else:
        # Unknown difficulty falls through to 'hard' (mirrors the original).
        full_right, full_wrong = CORRECT_HARD, INCORRECT_HARD

    return round(full_right * c + full_wrong * (1.0 - c))
