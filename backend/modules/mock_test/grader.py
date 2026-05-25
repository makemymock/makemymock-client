"""Server-side answer evaluation.

Set-based question types (multi_correct, matching) flatten their answer
shape to a pair of sets — `picked` and `correct` — and call
`policy_jaccard` to turn them into a correctness in [0, 1].

To swap the grading rule later: write another `policy_xxx(picked, correct)
-> float` function and replace the call sites in `grade_multi_correct` /
`grade_matching`.

Per question-type rules:
  single_correct  → selected_option ∈ correctOptions          (binary)
  multi_correct   → Jaccard on option keys                    (partial)
  integer         → numeric equality vs integerAnswer         (binary)
  matching        → Jaccard on flat (row, col) cell pairs     (partial)
  passage sub-Q   → graded as single_correct on its own        (binary)
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
# Grading policy
# ---------------------------------------------------------------------------

def policy_jaccard(picked: set, correct: set) -> float:
    """|picked ∩ correct| / |picked ∪ correct|.

    Symmetric: penalizes both omitted-correct and extra-wrong picks. Empty
    vs empty is treated as perfect (1.0) — vacuously, nothing was needed
    and nothing was picked.
    """
    union = picked | correct
    if not union:
        return 1.0
    return len(picked & correct) / len(union)


# ---------------------------------------------------------------------------
# Internal normalizers
# ---------------------------------------------------------------------------

def _as_option_set(values) -> set[str]:
    """Normalize MCQ-style option lists to upper-cased string set."""
    if values is None:
        return set()
    return {str(v).strip().upper() for v in values if v is not None and str(v).strip() != ""}


def _normalize_matching(raw) -> dict[str, set[str]]:
    """Coerce a stored / submitted mapping to dict[row_str, set[col_str]].

    Accepts the bbd_db storage shape `{ "0": [2, 3], ... }` (int values),
    the wire shape `{ "0": ["2", "3"], ... }` (string values), and tolerates
    legacy 1:1 shapes where the value is a single int/str.
    """
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


def _flatten_cells(row_map: dict[str, set[str]]) -> set[tuple[str, str]]:
    """{"0": {"2","3"}, "1": {"1"}} -> {("0","2"), ("0","3"), ("1","1")}."""
    return {(row, col) for row, cols in row_map.items() for col in cols}


# ---------------------------------------------------------------------------
# Graders — one per question type
# ---------------------------------------------------------------------------

def grade_single_correct(user_selected: Optional[str], doc: dict) -> GradedAnswer:
    correct_opts = _as_option_set(doc.get("correctOptions"))
    pick = str(user_selected).strip().upper() if user_selected else ""
    is_correct = bool(pick) and pick in correct_opts
    return GradedAnswer(
        is_correct=is_correct, correctness=None,
        user_answer=pick or None,
        correct_answer=sorted(correct_opts),
    )


def grade_multi_correct(user_selected, doc: dict) -> GradedAnswer:
    correct = _as_option_set(doc.get("correctOptions"))
    chosen  = _as_option_set(user_selected)
    score = policy_jaccard(chosen, correct)
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
    """Matrix-match grading.

    The (row, col) cells of the matrix are flattened to a single set, then
    handed to `policy_jaccard`. Wrong picks inflate the union and reduce the
    score symmetrically with missed-correct picks.

    Stored shape (bbd_db):
        matchingData.leftColumn:  [str, str, ...]              # n items
        matchingData.rightColumn: [str, str, ...]              # m items
        matchingData.correctMapping: { "0": [int,...], ... }   # row -> col idxs

    Wire shape (client → server):
        matching: { "0": ["2", "3"], "1": ["1"], ... }
    """
    md = doc.get("matchingData") or {}
    correct_rows = _normalize_matching(md.get("correctMapping"))
    chosen_rows  = _normalize_matching(user_mapping)

    score = policy_jaccard(
        _flatten_cells(chosen_rows),
        _flatten_cells(correct_rows),
    )

    return GradedAnswer(
        is_correct=(score >= 1.0 - 1e-9),
        correctness=float(score),
        user_answer={k: sorted(v) for k, v in chosen_rows.items()},
        correct_answer={k: sorted(v) for k, v in correct_rows.items()},
    )


def grade_passage_sub(user_selected: Optional[str], sub_doc: dict) -> GradedAnswer:
    """Sub-Qs of a passage are single_correct.

    bbd_db schema uses `correctOption` (singular string) for passage
    sub-questions, distinct from standalone questions which use
    `correctOptions` (array). We only check the singular form here.
    """
    raw_correct = sub_doc.get("correctOption")
    correct_set = (
        {raw_correct.strip().upper()}
        if isinstance(raw_correct, str) and raw_correct.strip()
        else set()
    )
    pick = str(user_selected).strip().upper() if user_selected else ""
    is_correct = bool(pick) and pick in correct_set
    return GradedAnswer(
        is_correct=is_correct, correctness=None,
        user_answer=pick or None,
        correct_answer=sorted(correct_set),
    )
