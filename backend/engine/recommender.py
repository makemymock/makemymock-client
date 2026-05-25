"""Orchestrator — wires the five layers together.

`create_mock_test()` reproduces `services_async.create_mock_test()`.
`submit_test()` reproduces `services_async.submit_mock_test()` minus the
actual answer-evaluation (the caller pre-evaluates each answer and passes
`AnswerEvaluation` objects).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

from engine.models import (
    AnswerEvaluation, Attempt, MockTest, SubmissionResult, TopicQuota,
)
from engine.priority import priority_scores_for_topics
from engine.distribution import distribute_by_priority
from engine.scoring import score_contribution, score_contribution_partial
from engine.selection import (
    select_questions, select_extra_performance_questions,
)


# Engine only needs structural conformance to the BufferedRepository
# adapter (modules/mock_test/engine_adapter.py). Typing as Any keeps the
# engine decoupled from its consumer.
from typing import Any as _Repository  # noqa: N812


# ---------------------------------------------------------------------------
# create_mock_test
# ---------------------------------------------------------------------------

def create_mock_test(
    repo: _Repository,
    *,
    user_id: Any,
    topic_ids: list[int],
    total_questions: int,
    include_extra: bool = False,
    extra_count: int = 0,
    shuffle_seed: int | None = None,
) -> MockTest:
    """Build a fresh mock test for the user.

    shuffle_seed: forwarded to select_questions. None preserves stable
    lead-id order; an int seeds the per-pool shuffle. In production, pass
    `int(time.time())` or a session-derived hash.
    """
    now = datetime.now(timezone.utc)

    # Pre-fetch all attempts for the selected topics.
    all_attempts = repo.get_attempts_for_topics(user_id, topic_ids)
    attempts_by_topic: dict[int, list[Attempt]] = defaultdict(list)
    for a in all_attempts:
        attempts_by_topic[a.topic_id].append(a)

    # Hierarchical cold-start: look up chapter_id for each selected topic so
    # the priority layer can borrow within-chapter when possible. Repository
    # implementations that don't have chapters return an empty dict, in
    # which case the engine falls back to flat borrowing.
    topic_chapters = repo.get_topic_chapter_ids(topic_ids) or None

    # Layer 2 — priority scores.
    priority_scores = priority_scores_for_topics(
        topic_ids, all_attempts, now, topic_chapters=topic_chapters,
    )

    # Layer 3 — distribution.
    distribution = distribute_by_priority(priority_scores, total_questions)

    # Persist the session shell + topic allocations.
    session_id = repo.save_session(
        user_id=user_id,
        total_questions=total_questions,
        extra_questions=extra_count if include_extra else 0,
        status="pending",
    )
    repo.save_topic_allocations(
        session_id,
        [(tid, distribution[tid], priority_scores[tid].score) for tid in distribution],
    )

    # Layer 4 + Layer 5 — fetch & select questions.
    available = repo.get_available_questions(topic_ids)
    selected, actual_allocation = select_questions(
        distribution=distribution,
        priority_scores=priority_scores,
        attempts_by_topic=attempts_by_topic,
        available_questions=available,
        target_total=total_questions,
        now=now,
        shuffle_seed=shuffle_seed,
    )

    # Optional extras.
    extras: list[tuple] = []
    if include_extra and extra_count > 0:
        # The original code queries questions across attempted-but-not-selected
        # topics. We fetch a wider available pool here by asking the repo
        # for questions in the topics the user has ever attempted.
        user_attempts = repo.get_attempts_for_user(user_id)
        all_attempted_topic_ids = {a.topic_id for a in user_attempts} - set(topic_ids)
        if all_attempted_topic_ids:
            extra_pool = repo.get_available_questions(list(all_attempted_topic_ids))
            already = {q.id for q, _ in selected}
            extras = select_extra_performance_questions(
                selected_topic_ids=topic_ids,
                user_attempts=user_attempts,
                available_questions=extra_pool,
                count=extra_count,
                already_selected_ids=already,
            )

    # Persist the blank response rows.
    response_rows = [(q.id, tid, False) for q, tid in selected]
    response_rows += [(q.id, tid, True) for q, tid in extras]
    repo.save_question_responses(session_id, response_rows)

    topic_quotas = [
        TopicQuota(
            topic_id=tid,
            question_count=actual_allocation.get(tid, 0),
            priority_score=priority_scores[tid].score,
            decay_factor=priority_scores[tid].decay_factor,
        )
        for tid in distribution
    ]

    return MockTest(
        session_id=session_id,
        user_id=user_id,
        total_questions=total_questions,
        extra_questions=extra_count if include_extra else 0,
        topics=topic_quotas,
        questions=selected,
        extras=extras,
    )


# ---------------------------------------------------------------------------
# submit_test
# ---------------------------------------------------------------------------

def submit_test(
    repo: _Repository,
    *,
    session_id: int,
    user_id: Any,
    evaluations: Iterable[AnswerEvaluation],
    difficulty_by_question: dict[int, str],
) -> SubmissionResult:
    """Update attempt history from the answer evaluations.

    The caller is responsible for answer-evaluation (the original code's
    `_evaluate_answer_batch` lives outside this engine — fuzzy matching of
    numeric answers, MCQ option lookup, etc. are not algorithmic, just IO).

    Required from caller per question:
      - `AnswerEvaluation(question_id, is_correct)`
      - the question's difficulty (so we can compute score_contribution)
    """
    now = datetime.now(timezone.utc)

    new_attempts: list[Attempt] = []
    correct = 0
    incorrect = 0
    partial = 0
    total_score = 0.0
    for e in evaluations:
        topic_id = repo.get_session_topic(session_id, e.question_id)
        if topic_id is None:
            continue
        difficulty = difficulty_by_question.get(e.question_id, "medium")
        if e.correctness is not None:
            # Partial credit (multi_correct, matching).
            sc = score_contribution_partial(e.correctness, difficulty)
            eff = e.correctness
        else:
            # Binary attempt — single_correct, integer, passage sub-Q.
            sc = score_contribution(e.is_correct, difficulty)
            eff = 1.0 if e.is_correct else 0.0
        new_attempts.append(Attempt(
            user_id=user_id,
            topic_id=topic_id,
            question_id=e.question_id,
            is_correct=e.is_correct,            # preserve caller's value as-is
            difficulty=difficulty,
            score_contribution=sc,
            attempted_at=now,
            correctness=e.correctness,
        ))
        total_score += eff
        # Bucket by effective_correctness with float tolerance.
        if eff >= 1.0 - 1e-9:
            correct += 1
        elif eff <= 1e-9:
            incorrect += 1
        else:
            partial += 1

    repo.upsert_attempts(new_attempts)
    repo.mark_session_completed(session_id)

    return SubmissionResult(
        session_id=session_id,
        correct=correct,
        incorrect=incorrect,
        partial=partial,
        total=correct + incorrect + partial,
        total_score=total_score,
        new_attempts=new_attempts,
    )
