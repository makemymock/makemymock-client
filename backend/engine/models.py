"""Lightweight dataclasses used throughout the engine.

These replace SQLAlchemy models in the original code. They carry only the
fields the algorithm reads, and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

# user_id is opaque to the engine — it's only stored on records and
# compared for equality (so the same object you pass in comes back out).
# Typing it as Any keeps the engine agnostic to whatever id type the
# consumer uses (ObjectId in our case, but it could be UUID, str, int…).
_UserId = Any


@dataclass(frozen=True)
class Question:
    """A question available to be served."""
    id: int
    topic_ids: tuple[int, ...]   # a question can be tagged to multiple topics
    difficulty: str              # 'easy' | 'medium' | 'hard'
    question_type: str = "single_correct"
    passage_id: Optional[int] = None


@dataclass(frozen=True)
class Attempt:
    """One user's most-recent attempt on one question.

    `correctness` is a fractional 0..1 grade for question types that admit
    partial credit (multi_correct, matching). For binary types
    (single_correct, integer, passage sub-Qs) it is None and consumers
    fall back to `is_correct` (1.0 / 0.0).
    """
    user_id: _UserId
    topic_id: int
    question_id: int
    is_correct: bool
    difficulty: str
    score_contribution: int
    attempted_at: datetime
    correctness: Optional[float] = None

    @property
    def effective_correctness(self) -> float:
        """0..1 grade — uses partial fraction when present, else binary."""
        if self.correctness is not None:
            return self.correctness
        return 1.0 if self.is_correct else 0.0


@dataclass(frozen=True)
class PriorityScore:
    """Output of Layer 2 for a single topic."""
    topic_id: int
    score: float           # final = base × decay
    base_score: float      # average of score_contribution
    decay_factor: float
    attempt_count: int


@dataclass(frozen=True)
class TopicQuota:
    """How many questions a topic was allocated for a test."""
    topic_id: int
    question_count: int
    priority_score: float
    decay_factor: float


@dataclass
class MockTest:
    """The output of create_mock_test()."""
    session_id: int
    user_id: _UserId
    total_questions: int
    extra_questions: int
    topics: list[TopicQuota]
    questions: list[tuple[Question, int]]        # (question, topic_id)
    extras: list[tuple[Question, int]] = field(default_factory=list)


@dataclass(frozen=True)
class AnswerEvaluation:
    """Input to submit_test: the user's answer + the verdict for one question.

    `correctness` carries a fractional 0..1 grade for partial-credit types
    (multi_correct, matching). When None, the engine derives 1.0 / 0.0
    from `is_correct`.
    """
    question_id: int
    is_correct: bool
    correctness: Optional[float] = None


@dataclass(frozen=True)
class SubmissionResult:
    """Per-test submission summary.

    Bucket counts (`correct`, `incorrect`, `partial`) describe the *shape*
    of the answers; `total_score` is the actual score (sum of fractional
    correctness across attempts). For a 20-question test where every
    multi_correct was 0.7 and everything else was fully right or wrong,
    `total_score` is the truthful figure; the bucket counts are
    informational.
    """
    session_id: int
    correct: int            # number of attempts with effective_correctness == 1.0
    incorrect: int          # number with effective_correctness == 0.0
    partial: int            # number where 0 < effective_correctness < 1
    total: int
    total_score: float      # Σ effective_correctness — the real score
    new_attempts: list[Attempt]
