"""Server-side answer evaluation.

Per question-type rules (see DECISIONS.md §5):
  single_correct  → selected_option ∈ correctOptions          (binary)
  multi_correct   → Jaccard |U∩C|/|U∪C|                       (partial)
  integer         → numeric equality vs integerAnswer         (binary)
  matching        → matches/total                              (partial)
  passage sub-Q   → graded as single_correct on its own
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class GradedAnswer:
    is_correct: bool
    correctness: Optional[float]   # None for binary types, float for partial
    user_answer: Any
    correct_answer: Any


# ---------------------------------------------------------------------------

def _as_set(values) -> set[str]:
    if values is None:
        return set()
    return {str(v).strip().upper() for v in values if v is not None and str(v).strip() != ""}


def grade_single_correct(user_selected: Optional[str], doc: dict) -> GradedAnswer:
    correct_opts = _as_set(doc.get("correctOptions"))
    pick = str(user_selected).strip().upper() if user_selected else ""
    is_correct = bool(pick) and pick in correct_opts
    return GradedAnswer(
        is_correct=is_correct, correctness=None,
        user_answer=pick or None,
        correct_answer=sorted(correct_opts),
    )


def grade_multi_correct(user_selected, doc: dict) -> GradedAnswer:
    """Jaccard-based partial credit."""
    correct = _as_set(doc.get("correctOptions"))
    chosen = _as_set(user_selected)
    if not correct and not chosen:
        return GradedAnswer(True, 1.0, [], [])
    union = correct | chosen
    inter = correct & chosen
    score = (len(inter) / len(union)) if union else 0.0
    return GradedAnswer(
        is_correct=(score >= 1.0 - 1e-9),
        correctness=float(score),
        user_answer=sorted(chosen),
        correct_answer=sorted(correct),
    )


def grade_integer(user_value: Any, doc: dict) -> GradedAnswer:
    correct_val = doc.get("integerAnswer")
    try:
        user_num = float(str(user_value).strip()) if user_value not in (None, "") else None
    except (TypeError, ValueError):
        user_num = None
    try:
        correct_num = float(correct_val) if correct_val is not None else None
    except (TypeError, ValueError):
        correct_num = None

    if user_num is None or correct_num is None:
        return GradedAnswer(False, None, user_value, correct_val)
    is_correct = abs(user_num - correct_num) < 1e-9
    return GradedAnswer(
        is_correct=is_correct, correctness=None,
        user_answer=user_value, correct_answer=correct_val,
    )


def grade_matching(user_mapping, doc: dict) -> GradedAnswer:
    md = doc.get("matchingData") or {}
    correct_mapping = md.get("correctMapping") or {}
    if isinstance(correct_mapping, list):
        # Normalize list-of-pairs → dict.
        try:
            correct_mapping = dict(correct_mapping)
        except Exception:
            correct_mapping = {}
    correct = {str(k).strip(): str(v).strip() for k, v in correct_mapping.items()}
    chosen = (user_mapping or {})
    chosen = {str(k).strip(): str(v).strip()
              for k, v in chosen.items() if v is not None}

    if not correct:
        return GradedAnswer(False, None, chosen, correct)

    matches = sum(1 for k, v in correct.items() if chosen.get(k) == v)
    score = matches / len(correct)
    return GradedAnswer(
        is_correct=(score >= 1.0 - 1e-9),
        correctness=float(score),
        user_answer=chosen,
        correct_answer=correct,
    )


def grade_passage_sub(user_selected: Optional[str], sub_doc: dict) -> GradedAnswer:
    """A passage sub-Q is single_correct on its own correctOption(s)."""
    raw_correct = sub_doc.get("correctOption")
    if raw_correct is None:
        raw_correct = sub_doc.get("correctOptions")
    if isinstance(raw_correct, str):
        correct_set = {raw_correct.strip().upper()} if raw_correct.strip() else set()
    else:
        correct_set = _as_set(raw_correct)
    pick = str(user_selected).strip().upper() if user_selected else ""
    is_correct = bool(pick) and pick in correct_set
    return GradedAnswer(
        is_correct=is_correct, correctness=None,
        user_answer=pick or None,
        correct_answer=sorted(correct_set),
    )
