"""Grade a jee_mains_pyqs answer.

Unlocking is "any submission counts", so grading is only for feedback — showing
the student whether they got it right and what the correct answer was. Mirrors
the mock-test grading semantics for the three jee_mains_pyqs types.
"""

from __future__ import annotations

from typing import Any, Union

from modules.pattern_learning.constants import (
    QUESTION_TYPE_INTEGER,
    QUESTION_TYPE_MULTI,
)

Answer = Union[str, list[str]]


def _as_list(answer: Answer) -> list[str]:
    if isinstance(answer, list):
        return [str(a).strip() for a in answer if str(a).strip()]
    return [answer.strip()] if str(answer).strip() else []


def _num_equal(a: str, b: Any) -> bool:
    try:
        return abs(float(str(a).strip()) - float(str(b).strip())) < 1e-9
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


def grade(question: dict, user_answer: Answer) -> tuple[bool, dict]:
    """Return (is_correct, correct) where `correct` describes the right answer
    for display: {"options": [...]} for mcq/mcqm, {"value": "..."} for integer.
    """
    qtype = (question.get("type") or "").lower()
    correct_options = [str(c).strip() for c in (question.get("correct_options") or [])]

    if qtype == QUESTION_TYPE_INTEGER:
        value = question.get("answer")
        picked = _as_list(user_answer)
        is_correct = bool(picked) and _num_equal(picked[0], value)
        return is_correct, {"value": "" if value is None else str(value)}

    if qtype == QUESTION_TYPE_MULTI:
        is_correct = set(_as_list(user_answer)) == set(correct_options)
        return is_correct, {"options": correct_options}

    # Default: single-correct mcq.
    picked = _as_list(user_answer)
    is_correct = bool(picked) and len(correct_options) == 1 and picked[0] == correct_options[0]
    return is_correct, {"options": correct_options}
