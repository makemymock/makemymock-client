"""Server-side answer evaluation for contests.

Pure-function port of `modules/mock_test/grader.py`, scoped to the
question types the contest UI/picker supports today: single_correct,
multi_correct, integer, matching. Passage questions are excluded by
the admin picker so the contest path never has to handle them.

Keeping the grader inside `contest/` (rather than sharing one from
`core/`) mirrors the project rule that `mock_test/` owns its grader.
We get a clear blast radius: changing scoring policy here only affects
contests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class GradedAnswer:
    is_correct: bool
    correctness: float          # 1.0 for fully correct, 0.0 for fully wrong,
                                # in between for partial-credit types.
    user_answer: Any
    correct_answer: Any


def _policy_jaccard(picked: set, correct: set) -> float:
    union = picked | correct
    if not union:
        return 1.0
    return len(picked & correct) / len(union)


def _as_option_set(values) -> set[str]:
    if values is None:
        return set()
    return {str(v).strip().upper() for v in values if v is not None and str(v).strip() != ""}


def _normalize_matching(raw) -> dict[str, set[str]]:
    if not raw:
        return {}
    out: dict[str, set[str]] = {}
    for k, v in raw.items():
        key = str(k).strip()
        if v is None:
            picks: set[str] = set()
        elif isinstance(v, (list, tuple, set)):
            picks = {str(x).strip() for x in v if x is not None and str(x).strip() != ""}
        else:
            s = str(v).strip()
            picks = {s} if s else set()
        out[key] = picks
    return out


def _flatten_cells(rows: dict[str, set[str]]) -> set[tuple[str, str]]:
    return {(r, c) for r, cols in rows.items() for c in cols}


# --------------------- per-type graders ---------------------

def grade_single_correct(user_selected: Optional[str], doc: dict) -> GradedAnswer:
    correct = _as_option_set(doc.get("correctOptions"))
    pick = str(user_selected).strip().upper() if user_selected else ""
    ok = bool(pick) and pick in correct
    return GradedAnswer(
        is_correct=ok,
        correctness=1.0 if ok else 0.0,
        user_answer=pick or None,
        correct_answer=sorted(correct),
    )


def grade_multi_correct(user_selected, doc: dict) -> GradedAnswer:
    correct = _as_option_set(doc.get("correctOptions"))
    chosen = _as_option_set(user_selected)
    score = _policy_jaccard(chosen, correct)
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
        return GradedAnswer(False, 0.0, user_value, correct_val)
    ok = abs(user_num - correct_num) < 1e-9
    return GradedAnswer(ok, 1.0 if ok else 0.0, user_value, correct_val)


def grade_matching(user_mapping, doc: dict) -> GradedAnswer:
    md = doc.get("matchingData") or {}
    correct_rows = _normalize_matching(md.get("correctMapping"))
    chosen_rows = _normalize_matching(user_mapping)
    score = _policy_jaccard(_flatten_cells(chosen_rows), _flatten_cells(correct_rows))
    return GradedAnswer(
        is_correct=(score >= 1.0 - 1e-9),
        correctness=float(score),
        user_answer={k: sorted(v) for k, v in chosen_rows.items()},
        correct_answer={k: sorted(v) for k, v in correct_rows.items()},
    )


# --------------------- dispatcher + scoring ---------------------

def grade_answer(qtype: str, answer: dict, doc: dict) -> GradedAnswer:
    """Dispatch one submitted answer to the right per-type grader.

    `answer` is the wire-shape dict from the client (single field set per
    qtype — `selected_option` / `selected_options` / `integer_answer`
    / `matching`).
    """
    qtype = (qtype or "").lower()
    if qtype == "single_correct":
        return grade_single_correct(answer.get("selected_option"), doc)
    if qtype == "multi_correct":
        return grade_multi_correct(answer.get("selected_options") or [], doc)
    if qtype == "integer":
        return grade_integer(answer.get("integer_answer"), doc)
    if qtype == "matching":
        return grade_matching(answer.get("matching") or {}, doc)
    # Defensive default — never trust an unknown type to be "correct".
    return GradedAnswer(False, 0.0, None, None)


def is_attempt_empty(qtype: str, answer: Optional[dict]) -> bool:
    """An attempt is empty when the user submitted nothing for that
    question (we don't penalise as `wrong` — they get the unattempted
    marks instead)."""
    if not answer:
        return True
    qtype = (qtype or "").lower()
    if qtype == "single_correct":
        return not (answer.get("selected_option") or "").strip()
    if qtype == "multi_correct":
        return not (answer.get("selected_options") or [])
    if qtype == "integer":
        v = answer.get("integer_answer")
        return v is None or str(v).strip() == ""
    if qtype == "matching":
        m = answer.get("matching") or {}
        return not any((cols or []) for cols in m.values())
    return True


def score_for(graded: GradedAnswer, marking: dict, empty: bool) -> float:
    """Apply the contest's marking scheme to a graded answer.

    Partial-credit types (multi_correct, matching) award
    `correctness * correct` for non-empty attempts. Fully correct gets
    the full positive mark; anything less than 1 but positive falls in
    between. Fully empty → unattempted. Anything else (wrong attempt
    on a binary type, or zero-correctness on a partial type) → wrong.
    """
    correct = float(marking.get("correct", 0))
    wrong = float(marking.get("wrong", 0))
    unattempted = float(marking.get("unattempted", 0))

    if empty:
        return unattempted
    if graded.is_correct:
        return correct
    if graded.correctness > 0:
        return graded.correctness * correct
    return wrong
