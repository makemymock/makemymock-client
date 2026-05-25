# Grading policy

How partial-credit question types (`multi_correct`, `matching`) are scored,
and how to change that rule.

All grading code lives in
[`backend/modules/mock_test/grader.py`](backend/modules/mock_test/grader.py).

## TL;DR

- One rule today: **Jaccard** — `|picked ∩ correct| / |picked ∪ correct|`.
- It's applied to two set-based question types:
  - `multi_correct` → sets of option keys (`{A, C}` vs `{A, B, C}`).
  - `matching` → sets of `(row, col)` cell pairs flattened from the matrix.
- Binary types (`single_correct`, `integer`, passage sub-Qs) have no policy
  — they're a direct correct/incorrect check.
- To swap the rule: write a new `policy_xxx(picked, correct) -> float`
  next to `policy_jaccard`, then change **two call sites** in
  `grade_multi_correct` and `grade_matching`.

## What "correctness" feeds

The grader returns `correctness ∈ [0, 1]` for set-based types (or `None`
for binary types). That number is the only thing downstream code sees:

```
grader → correctness
       → engine/scoring.score_contribution_partial(correctness, difficulty)
       → int score_contribution persisted on Attempt
       → enters topic priority weighted mean
       → next-test allocator reads topic priority
```

So changing the grading policy changes correctness, which changes
`score_contribution`, which changes topic priority. The downstream engine
is policy-agnostic.

## Policy contract

A grading policy is a pure function:

```python
def policy_xxx(picked: set, correct: set) -> float:
    """Return correctness in [0, 1]."""
```

- `picked` and `correct` are **sets** of hashable elements. Element type
  doesn't matter to the policy — it's option-letter strings for
  `multi_correct` and `(row, col)` tuples for `matching`.
- Convention: empty `picked` and empty `correct` ⇒ return `1.0` (vacuously
  perfect). The current Jaccard implementation does this.

## How to add a new policy

1. Open
   [`backend/modules/mock_test/grader.py`](backend/modules/mock_test/grader.py).
2. Add the function next to `policy_jaccard`:

   ```python
   def policy_recall(picked: set, correct: set) -> float:
       if not correct:
           return 1.0 if not picked else 0.0
       return len(picked & correct) / len(correct)
   ```

3. Change the call sites that should use it. There are two:

   ```python
   # in grade_multi_correct
   score = policy_jaccard(chosen, correct)   # ← swap to policy_recall(...)

   # in grade_matching
   score = policy_jaccard(
       _flatten_cells(chosen_rows),
       _flatten_cells(correct_rows),
   )   # ← same here
   ```

4. (Optional) Apply the change to only one type by leaving the other
   call site untouched. Matrix-match and multi-correct are independent.

That's it — no registries, no config, no migration. The next attempt
submitted goes through the new rule.

## How a policy change propagates

- **Forward-only.** Each `Attempt` row stores its `correctness` and
  `score_contribution` at submit time
  ([`engine/recommender.py`](backend/engine/recommender.py)). Existing
  attempts in `user_topic_attempts` keep their old values. Topic priorities
  recompute from those persisted ints, so they drift only as new attempts
  come in.
- **Result-page bucketing changes too.** The "correct / partial / incorrect"
  count on the result page is bucketed from `correctness` thresholds
  ([`engine/recommender.py`](backend/engine/recommender.py)): `1.0`
  → correct, `0.0` → incorrect, anything else → partial. A new policy
  that smooths over more cases (e.g. Jaccard punishing tick-everything)
  shifts more attempts into the "partial" bucket on the UI.
- **No frontend change required.** The wire shape of `correctness`,
  `is_correct`, `user_answer`, `correct_answer` is unchanged regardless
  of policy.

## Worked example: Jaccard on a real matrix-match question

Question (4 left rows, 6 right columns, 7 correct cells):

```
correctMapping = { "0":[2,3], "1":[0,1], "2":[4], "3":[4,5] }
total correct cells = 7  (out of 4 × 6 = 24 cells)
```

| Scenario | hits | wrong | missed | correctness |
|---|---:|---:|---:|---:|
| Exact answer | 7 | 0 | 0 | `7/7 = 1.000` |
| 5/7 right, 0 wrong | 5 | 0 | 2 | `5/7 ≈ 0.714` |
| 5/7 right, 1 wrong | 5 | 1 | 2 | `5/8 = 0.625` |
| All 7 right + 3 wrong extras | 7 | 3 | 0 | `7/10 = 0.700` |
| Tick everything (24 cells) | 7 | 17 | 0 | `7/24 ≈ 0.292` |
| Empty answer | 0 | 0 | 7 | `0/7 = 0.000` |

For `medium` difficulty
(`CORRECT_MEDIUM=2`, `INCORRECT_MEDIUM=8` from
[`engine/config.py`](backend/engine/config.py)), the `score_contribution`
for `correctness = 0.625` is
`round(2·0.625 + 8·0.375) = round(4.25) = 4`. That `4` is what enters
the topic's priority mean.

## Common alternative policies (paste-ready)

```python
def policy_recall(picked, correct):
    if not correct:
        return 1.0 if not picked else 0.0
    return len(picked & correct) / len(correct)


def policy_precision(picked, correct):
    if not picked:
        return 1.0 if not correct else 0.0
    return len(picked & correct) / len(picked)


def policy_f1(picked, correct):
    p = policy_precision(picked, correct)
    r = policy_recall(picked, correct)
    return (2 * p * r / (p + r)) if (p + r) else 0.0


def policy_strict_recall(picked, correct):
    """JEE-Advanced flavor: zero credit if any wrong pick."""
    if picked - correct:
        return 0.0
    return policy_recall(picked, correct)
```

Behavior summary on the matrix-match "5 hits + 1 wrong + 2 missed" case
above (7 correct cells total):

| Policy | correctness |
|---|---:|
| `jaccard`        | `5/8 = 0.625` |
| `recall`         | `5/7 ≈ 0.714` |
| `precision`      | `5/6 ≈ 0.833` |
| `f1`             | `0.769` |
| `strict_recall`  | `0.0` (any wrong pick zeros it) |

## Things that are NOT policies

These are intentionally not pluggable; changing them requires touching the
engine, not just the grader:

- **Per-attempt weight by question type.** Each question contributes one
  `Attempt` row regardless of question complexity (matrix-match with 7
  cells = same weight as a single_correct in the topic mean). Discussed in
  the `# question-weight` thread of `DECISIONS.md`; tracked for future
  work.
- **`score_contribution_partial` formula.** The linear interpolation from
  `correctness ∈ [0, 1]` to int `score_contribution ∈ [CORRECT_DIFF,
  INCORRECT_DIFF]` lives in
  [`engine/scoring.py`](backend/engine/scoring.py). Constants in
  [`engine/config.py`](backend/engine/config.py).
- **Recency decay + step-function in priority.** Lives in
  [`engine/priority.py`](backend/engine/priority.py).
- **Passage sub-Q handling.** Each sub-Q is *already* a separate Attempt
  in the engine, so they have their own correctness signal individually
  — no extra policy needed for passage.
