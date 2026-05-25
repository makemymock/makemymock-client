"""Pydantic request/response models for mock-test endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

class CatalogTopic(BaseModel):
    id: int
    chapter_id: int
    name: str
    question_count: int


class CatalogChapter(BaseModel):
    id: int
    subject_id: int
    name: str
    topics: list[CatalogTopic]


class CatalogSubject(BaseModel):
    id: int
    name: str
    chapters: list[CatalogChapter]


class CatalogResponse(BaseModel):
    subjects: list[CatalogSubject]


# ---------------------------------------------------------------------------
# Create test
# ---------------------------------------------------------------------------

class CreateMockTestRequest(BaseModel):
    topic_ids: list[int] = Field(..., min_length=1, max_length=200)
    # ge=1 — the regular Tests UI clamps to 10/20/30/50, but Problem-of-the-Day
    # legitimately creates a 1-question session (see USING_THE_ENGINE.md §4.1).
    # 100 stays as a hard upper bound so a runaway client can't ask for huge tests.
    total_questions: int = Field(..., ge=1, le=100)
    extra_questions: int = Field(0, ge=0, le=20)


class QuestionPayloadOption(BaseModel):
    # Images embedded inline via markdown in `text` — no separate field.
    key: str
    text: str


class QuestionPayload(BaseModel):
    """A test-taking-safe question payload — answers are stripped.

    `extra="forbid"` ensures that a future bug like `QuestionPayload(**raw_doc)`
    would raise at construction instead of silently passing through
    `correctOptions` / `solution` / `integerAnswer` to the client.
    """

    model_config = ConfigDict(extra="forbid")

    question_id: int
    topic_id: int
    display_order: int
    question_type: str
    difficulty: str
    is_extra: bool = False

    # Passage grouping (sub-questions of a passage share a passage_id and
    # carry the passage text on every sibling so the client can render).
    passage_id: Optional[int] = None
    passage_text: Optional[str] = None
    passage_sub_index: Optional[int] = None
    passage_sub_total: Optional[int] = None

    # Content. Images live inline as markdown inside `question_text`.
    question_text: str = ""

    # Single/multi-correct
    options: list[QuestionPayloadOption] = Field(default_factory=list)

    # Matching — bare LaTeX strings; the client renders them with row/column
    # headers `P1..Pn` / `Q1..Qm` derived from their list indices, and the
    # answer wire format uses those same indices as string keys.
    left_column: list[str] = Field(default_factory=list)
    right_column: list[str] = Field(default_factory=list)


class CreateMockTestResponse(BaseModel):
    session_id: int
    total_questions: int
    extra_questions: int
    total_seconds: int
    status: str
    created_at: datetime
    topics: list[dict[str, Any]] = Field(default_factory=list)
    questions: list[QuestionPayload] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Fetch session
# ---------------------------------------------------------------------------

class SessionResponse(CreateMockTestResponse):
    """Same shape as create response — used for resuming a session."""


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

class AnswerInput(BaseModel):
    """A single submitted answer.

    Exactly one of these fields should be set for each question_id,
    depending on the question's type:
      - single_correct      → selected_option (str, single key)
      - multi_correct       → selected_options (list[str])
      - integer             → integer_answer (number or numeric string)
      - matching            → matching (dict[left_idx_str, list[right_idx_str]])
      - passage sub-Q       → selected_option (treated as single_correct)
    """

    question_id: int
    selected_option: Optional[str] = None
    selected_options: Optional[list[str]] = None
    integer_answer: Optional[Any] = None
    matching: Optional[dict[str, list[str]]] = None


class SubmitMockTestRequest(BaseModel):
    answers: list[AnswerInput] = Field(default_factory=list)


class PerQuestionResult(BaseModel):
    question_id: int
    topic_id: int
    display_order: int
    is_correct: bool
    correctness: float
    user_answer: Any = None
    correct_answer: Any = None
    difficulty: str
    question_type: str
    score_contribution: int
    # Question content + solution — populated by `get_results` so the
    # review screen can show the prompt and explanation side by side.
    # Images for question/passage/solution are embedded inline as markdown.
    question_text: Optional[str] = None
    options: list[QuestionPayloadOption] = Field(default_factory=list)
    left_column: list[str] = Field(default_factory=list)
    right_column: list[str] = Field(default_factory=list)
    passage_text: Optional[str] = None
    passage_sub_index: Optional[int] = None
    passage_sub_total: Optional[int] = None
    passage_id: Optional[int] = None
    solution_text: Optional[str] = None


class SubmitMockTestResponse(BaseModel):
    session_id: int
    total: int
    correct: int
    incorrect: int
    partial: int
    total_score: float
    max_score: float
    accuracy_pct: float
    results: list[PerQuestionResult]


# ---------------------------------------------------------------------------
# History / analytics
# ---------------------------------------------------------------------------

class HistoryItem(BaseModel):
    session_id: int
    created_at: datetime
    completed_at: Optional[datetime] = None
    status: str
    total_questions: int
    correct: Optional[int] = None
    incorrect: Optional[int] = None
    partial: Optional[int] = None
    score: Optional[float] = None
    accuracy_pct: Optional[float] = None


class HistoryResponse(BaseModel):
    items: list[HistoryItem]


class TopicAnalytics(BaseModel):
    topic_id: int
    topic_name: str
    chapter_name: str
    subject_name: str
    attempts: int
    correct: int
    accuracy_pct: float
    priority_score: float
    decay_factor: float
    last_attempted_at: Optional[datetime] = None


class DifficultyBreakdown(BaseModel):
    difficulty: str
    attempts: int
    correct: int
    accuracy_pct: float


class TypeBreakdown(BaseModel):
    question_type: str
    attempts: int
    correct: int
    accuracy_pct: float


class TrendPoint(BaseModel):
    session_id: int
    completed_at: datetime
    accuracy_pct: float
    score: float


class AnalyticsOverviewResponse(BaseModel):
    total_tests: int
    total_questions: int
    overall_accuracy_pct: float
    total_score: float
    by_difficulty: list[DifficultyBreakdown]
    by_type: list[TypeBreakdown]
    weakest_topics: list[TopicAnalytics]
    strongest_topics: list[TopicAnalytics]
    trend: list[TrendPoint]


class AnalyticsTopicsResponse(BaseModel):
    topics: list[TopicAnalytics]


# ---------------------------------------------------------------------------
# Chapter analytics
# ---------------------------------------------------------------------------

class ChapterAnalytics(BaseModel):
    chapter_id: int
    chapter_name: str
    subject_id: int
    subject_name: str
    attempted_topic_count: int
    total_topic_count: int
    attempts: int
    correct: int
    accuracy_pct: float
    avg_priority_score: float
    max_priority_score: float
    avg_decay_factor: float
    last_attempted_at: Optional[datetime] = None


class AnalyticsChaptersResponse(BaseModel):
    chapters: list[ChapterAnalytics]


# ---------------------------------------------------------------------------
# Trend points reused by chapter/topic detail
# ---------------------------------------------------------------------------

class PriorityTrendPoint(BaseModel):
    session_id: int
    completed_at: datetime
    priority_score: float
    decay_factor: float


class AccuracyTrendPoint(BaseModel):
    session_id: int
    completed_at: datetime
    accuracy_pct: float
    attempts: int
    correct: int


class CumulativePoint(BaseModel):
    date: datetime
    delta: int
    cumulative: int


class TopicPriorityTrend(BaseModel):
    topic_id: int
    topic_name: str
    points: list[PriorityTrendPoint]


class TopicAccuracyTrend(BaseModel):
    topic_id: int
    topic_name: str
    points: list[AccuracyTrendPoint]


# ---------------------------------------------------------------------------
# Chapter detail (one chapter, drilled down)
# ---------------------------------------------------------------------------

class ChapterDetailResponse(BaseModel):
    chapter_id: int
    chapter_name: str
    subject_id: int
    subject_name: str
    attempts: int
    correct: int
    accuracy_pct: float
    total_score: float
    avg_priority_score: float
    max_priority_score: float
    avg_decay_factor: float
    last_attempted_at: Optional[datetime] = None
    topics: list[TopicAnalytics]
    priority_trend: list[PriorityTrendPoint]
    accuracy_trend: list[AccuracyTrendPoint]
    cumulative_attempts: list[CumulativePoint]
    by_difficulty: list[DifficultyBreakdown]
    by_type: list[TypeBreakdown]
    per_topic_priority: list[TopicPriorityTrend]
    per_topic_accuracy: list[TopicAccuracyTrend]


# ---------------------------------------------------------------------------
# Topic detail (one topic, drilled down)
# ---------------------------------------------------------------------------

class RecentAttempt(BaseModel):
    session_id: int
    question_id: int
    attempted_at: datetime
    is_correct: bool
    correctness: float
    difficulty: str
    score_contribution: int


class TopicDetailResponse(BaseModel):
    topic_id: int
    topic_name: str
    chapter_id: int
    chapter_name: str
    subject_id: int
    subject_name: str
    attempts: int
    correct: int
    accuracy_pct: float
    current_priority_score: float
    current_decay_factor: float
    last_attempted_at: Optional[datetime] = None
    priority_trend: list[PriorityTrendPoint]
    accuracy_trend: list[AccuracyTrendPoint]
    cumulative_attempts: list[CumulativePoint]
    by_difficulty: list[DifficultyBreakdown]
    by_type: list[TypeBreakdown]
    recent_attempts: list[RecentAttempt]
