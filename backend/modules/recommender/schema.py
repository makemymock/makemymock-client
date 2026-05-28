"""
Pydantic v2 request and response models for the JEE Recommender API.

Controllers import from here; services return instances of these models.
No business logic lives here — only shape, validation, and serialization.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Session state — passed on every per-question call to maintain the hot loop
# without a server-side session store
# ---------------------------------------------------------------------------

class SessionState(BaseModel):
    """
    Client-maintained session state. Returned after each answer, echoed back
    on the next next-question request. Keeps the hot path stateless server-side.
    """
    consecutive_wrong: int = 0
    questions_asked: int = 0
    session_mode: Literal["normal", "recovery", "wind_down"] = "normal"
    # question_ids already served and answered correctly (exclude from candidates)
    seen_correct_ids: list[str] = Field(default_factory=list)
    # All question_ids served this session (exclude from spaced-repetition injection)
    seen_all_ids: list[str] = Field(default_factory=list)
    # Tracks per-block accuracy for fatigue profiling
    block_correct: list[int] = Field(default_factory=lambda: [0, 0, 0])
    block_total: list[int] = Field(default_factory=lambda: [0, 0, 0])


# ---------------------------------------------------------------------------
# Student initialization
# ---------------------------------------------------------------------------

class InitializeStudentResponse(BaseModel):
    student_id: str
    topics_initialized: int
    personality_created: bool
    message: str


# ---------------------------------------------------------------------------
# Session start — Phase A
# ---------------------------------------------------------------------------

class StartSessionRequest(BaseModel):
    pass  # student_id is derived from the bearer token in the controller


class SessionPlanResponse(BaseModel):
    """
    Output of the Session Planner Agent. Returned to the client at session
    start and used to pre-filter the candidate topic pool for the whole session.
    """
    student_id: str
    session_id: str
    focus_topics: list[str]
    session_mode: Literal["drilling", "review", "mixed", "recovery"]
    start_difficulty_offset: float
    review_injection_rate: float
    confidence_note: str
    reasoning_steps: list[str] = Field(default_factory=list)
    state: SessionState


# ---------------------------------------------------------------------------
# Next question — Phase B (hot loop)
# ---------------------------------------------------------------------------

class NextQuestionRequest(BaseModel):
    # student_id is derived from the bearer token in the controller
    session_id: str
    focus_topics: list[str]
    start_difficulty_offset: float
    review_injection_rate: float
    state: SessionState


class NextQuestionResponse(BaseModel):
    """
    Single question selected by the hot loop (math + agent). The client uses
    question_id to fetch the full question from the existing /mock-test/browse
    endpoint — this service does not duplicate question content.
    """
    question_id: str
    topic_id: str
    chapter: str
    difficulty_target: float
    is_review_injection: bool
    session_mode: Literal["normal", "recovery", "wind_down"]
    difficulty_offset_applied: float


# ---------------------------------------------------------------------------
# Answer submission — Phase C
# ---------------------------------------------------------------------------

class SubmitAnswerRequest(BaseModel):
    # student_id is derived from the bearer token in the controller
    session_id: str
    question_id: str
    topic_id: str
    chapter: str
    correct: bool
    time_ms: int = Field(..., ge=0)
    difficulty: float
    question_type: str
    state: SessionState


class TopicMasteryUpdate(BaseModel):
    topic_id: str
    chapter: str
    alpha: int
    beta: int
    mastery_mean: float
    theta: float
    next_review_date: str


class SubmitAnswerResponse(BaseModel):
    """
    Returned immediately after an answer is processed. Contains the updated
    session state and any topics that just became unlocked.
    """
    updated_topic: TopicMasteryUpdate
    newly_unlocked_topics: list[str]
    state: SessionState
    frustration_triggered: bool
    diagnosis_triggered: bool


# ---------------------------------------------------------------------------
# End session — triggers async Diagnosis Agent
# ---------------------------------------------------------------------------

class EndSessionRequest(BaseModel):
    # student_id is derived from the bearer token in the controller
    session_id: str
    state: SessionState
    started_at: datetime


class EndSessionResponse(BaseModel):
    session_id: str
    summary_id: str
    diagnosis_triggered: bool
    message: str


# ---------------------------------------------------------------------------
# Student personality
# ---------------------------------------------------------------------------

class QuestionTypeStrengths(BaseModel):
    single_correct: float
    multi_correct: float
    integer: float
    matching: float


class StudentPersonalityResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    student_id: str
    learning_style: str
    fatigue_threshold_questions: int
    confidence_profile: str
    improvement_rate: str
    strong_chapters: list[str]
    persistent_weak_chapters: list[str]
    avoidance_topics: list[str]
    question_type_strengths: QuestionTypeStrengths
    error_profile: dict[str, str]
    notes: str
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Topic states
# ---------------------------------------------------------------------------

class TopicStateResponse(BaseModel):
    student_id: str
    topic_id: str
    chapter: str
    alpha: int
    beta: int
    mastery_mean: float
    mastery_uncertainty: float
    theta: float
    next_review_date: str
    review_interval_days: int
    easiness_factor: float
    total_attempts: int
    total_correct: int
    last_attempted: Optional[datetime] = None
    is_unlocked: bool = False


class AllTopicStatesResponse(BaseModel):
    student_id: str
    topic_states: list[TopicStateResponse]
    total: int
    unlocked_count: int


# ---------------------------------------------------------------------------
# Trend scores
# ---------------------------------------------------------------------------

class TopicTrendResponse(BaseModel):
    topic_id: str
    chapter: str
    p_appears: float
    trend_score_raw: float
    gap_bonus: float
    streak_score: float
    direction_multiplier: float
    computed_at: Optional[datetime] = None
    is_high_priority: bool = False


class AllTrendScoresResponse(BaseModel):
    topics: list[TopicTrendResponse]
    total: int
    high_priority_count: int
    computed_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Admin — weekly trend update trigger
# ---------------------------------------------------------------------------

class TrendUpdateResponse(BaseModel):
    status: Literal["triggered", "completed", "failed"]
    topics_updated: Optional[int] = None
    message: str


# ---------------------------------------------------------------------------
# Session history
# ---------------------------------------------------------------------------

class SessionSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str
    student_id: str
    duration_minutes: float
    questions_attempted: int
    accuracy_by_chapter: dict[str, float]
    frustration_events_count: int
    topics_unlocked: list[str]
    first_half_accuracy: float
    second_half_accuracy: float
    created_at: Optional[datetime] = None


class SessionHistoryResponse(BaseModel):
    sessions: list[SessionSummaryResponse]
    total: int


# ---------------------------------------------------------------------------
# Question detail — fetched by PYQ question_id for in-session display
# ---------------------------------------------------------------------------

class QuestionOption(BaseModel):
    identifier: str
    content: str


class QuestionDetailResponse(BaseModel):
    question_id: str
    question: str
    options: list[QuestionOption]
    correct_options: list[str] = []
    correct_answer: Optional[str] = None
    type: str
    chapter: str
    topic: str
    subject: str
    difficulty: str
    year: Optional[int] = None
    is_image_question: bool = False
    is_image_option: Any = False


class StudentStatsResponse(BaseModel):
    total_attempts: int
    total_correct: int
    accuracy: float
    topics_attempted: int
    topics_mastered: int
    unlocked_count: int
