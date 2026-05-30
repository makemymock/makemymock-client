from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class SessionState(BaseModel):
    consecutive_wrong: int = 0
    questions_asked: int = 0
    session_mode: Literal["normal", "recovery", "wind_down"] = "normal"
    seen_correct_ids: list[str] = Field(default_factory=list)
    seen_all_ids: list[str] = Field(default_factory=list)
    block_correct: list[int] = Field(default_factory=lambda: [0, 0, 0])
    block_total: list[int] = Field(default_factory=lambda: [0, 0, 0])


class InitializeStudentResponse(BaseModel):
    student_id: str
    topics_initialized: int
    personality_created: bool
    message: str


class StartSessionRequest(BaseModel):
    pass


class SessionPlanResponse(BaseModel):
    student_id: str
    session_id: str
    focus_topics: list[str]
    session_mode: Literal["drilling", "review", "mixed", "recovery"]
    start_difficulty_offset: float
    review_injection_rate: float
    confidence_note: str
    reasoning_steps: list[str] = Field(default_factory=list)
    state: SessionState


class NextQuestionRequest(BaseModel):
    session_id: str
    focus_topics: list[str]
    start_difficulty_offset: float
    review_injection_rate: float
    state: SessionState


class NextQuestionResponse(BaseModel):
    question_id: str
    topic_id: str
    chapter: str
    difficulty_target: float
    is_review_injection: bool
    session_mode: Literal["normal", "recovery", "wind_down"]
    difficulty_offset_applied: float
    review_reason: str = ""   # populated when is_review_injection=True


class SubmitAnswerRequest(BaseModel):
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
    updated_topic: TopicMasteryUpdate
    newly_unlocked_topics: list[str]
    state: SessionState
    frustration_triggered: bool
    diagnosis_triggered: bool


class EndSessionRequest(BaseModel):
    session_id: str
    state: SessionState
    started_at: datetime


class EndSessionResponse(BaseModel):
    session_id: str
    summary_id: str
    diagnosis_triggered: bool
    message: str


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


class TopicStateResponse(BaseModel):
    student_id: str
    topic_id: str
    chapter: str
    subject: str = "mathematics"
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


class TrendUpdateResponse(BaseModel):
    status: Literal["triggered", "completed", "failed"]
    topics_updated: Optional[int] = None
    message: str


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


# ── Attempted questions (correct / incorrect review) ─────────────────────────

class AttemptedQuestionItem(BaseModel):
    question_id: str
    topic_id: str
    chapter: str
    subject: str = "mathematics"
    correct: bool
    difficulty: Any = None
    question_type: str = "single_correct"
    timestamp: Optional[datetime] = None
    question_text: str = ""
    options: list[QuestionOption] = []
    correct_options: list[str] = []
    correct_answer: Optional[str] = None
    year: Optional[int] = None
    is_image_question: bool = False


class AttemptedQuestionsResponse(BaseModel):
    items: list[AttemptedQuestionItem]
    total: int


# ── Catalog subjects (for Physics / Chemistry selection) ─────────────────────

class CatalogChapterInfo(BaseModel):
    chapter: str
    topic_count: int


class CatalogSubjectInfo(BaseModel):
    subject: str
    chapters: list[CatalogChapterInfo]
    topic_count: int


class CatalogSubjectsResponse(BaseModel):
    subjects: list[CatalogSubjectInfo]
