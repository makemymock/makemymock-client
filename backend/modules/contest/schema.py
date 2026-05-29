"""Pydantic request/response models for student-facing contest endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class MarkingScheme(BaseModel):
    correct: float
    wrong: float
    unattempted: float


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------

class ContestListItem(BaseModel):
    """One row in the student's contest list — what they see in the
    Compete > Contest tab. `user_state` summarises their per-contest
    status so the UI can render the right CTA (enter lobby / waiting /
    in progress / view result)."""
    id: str
    title: str
    description: str
    start_time: datetime
    end_time: datetime
    duration_seconds: int
    question_count: int
    marking: MarkingScheme
    status: Literal["scheduled", "live", "completed"]
    lobby_opens_at: datetime
    lobby_open: bool
    user_state: Literal[
        "none",         # never interacted
        "entered",      # in lobby, contest not started
        "in_progress",  # started but not submitted
        "submitted",    # finished
        "missed",       # contest ended without participating
    ]


class ContestListResponse(BaseModel):
    upcoming: list[ContestListItem]
    live: list[ContestListItem]
    past: list[ContestListItem]


# ---------------------------------------------------------------------------
# Detail / lobby
# ---------------------------------------------------------------------------

class ContestLobbyResponse(BaseModel):
    """Detail returned on GET /contests/{id} — pre-start, the questions
    field is omitted. Once the user starts the contest the play endpoint
    serves the question payload."""
    id: str
    title: str
    description: str
    rules: str
    start_time: datetime
    end_time: datetime
    duration_seconds: int
    question_count: int
    marking: MarkingScheme
    status: Literal["scheduled", "live", "completed"]
    lobby_opens_at: datetime
    lobby_open: bool
    user_state: Literal["none", "entered", "in_progress", "submitted", "missed"]


class EnterLobbyResponse(BaseModel):
    user_state: Literal["entered", "in_progress", "submitted"]
    entered_at: datetime


# ---------------------------------------------------------------------------
# Play
# ---------------------------------------------------------------------------

class ContestOption(BaseModel):
    key: str
    text: str


class ContestQuestion(BaseModel):
    """Test-safe question payload — answers are stripped."""

    model_config = ConfigDict(extra="forbid")

    question_id: str
    display_order: int
    question_type: Literal["single_correct", "multi_correct", "integer", "matching"]
    difficulty: Optional[str] = None
    question_text: str = ""
    options: list[ContestOption] = Field(default_factory=list)
    left_column: list[str] = Field(default_factory=list)
    right_column: list[str] = Field(default_factory=list)


class StartContestResponse(BaseModel):
    contest_id: str
    started_at: datetime
    end_time: datetime
    duration_seconds: int
    server_now: datetime
    questions: list[ContestQuestion]


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

class ContestAnswerInput(BaseModel):
    """One submitted answer. Exactly one of the per-type fields should be
    set; the dispatcher routes by the question's stored type."""
    question_id: str
    selected_option: Optional[str] = None
    selected_options: Optional[list[str]] = None
    integer_answer: Optional[Any] = None
    matching: Optional[dict[str, list[str]]] = None


class SubmitContestRequest(BaseModel):
    answers: list[ContestAnswerInput] = Field(default_factory=list)


class ContestPerQuestionResult(BaseModel):
    question_id: str
    display_order: int
    question_type: str
    difficulty: Optional[str] = None
    question_text: str = ""
    options: list[ContestOption] = Field(default_factory=list)
    left_column: list[str] = Field(default_factory=list)
    right_column: list[str] = Field(default_factory=list)
    user_answer: Any = None
    correct_answer: Any = None
    is_correct: bool
    correctness: float
    marks_awarded: float
    solution_text: Optional[str] = None


class ContestResultResponse(BaseModel):
    contest_id: str
    title: str
    total_questions: int
    correct_count: int
    wrong_count: int
    unattempted_count: int
    score: float
    max_score: float
    accuracy_pct: float
    time_taken_seconds: int
    submitted_at: datetime
    rank: int
    total_participants: int
    results: list[ContestPerQuestionResult]


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

class LeaderboardRow(BaseModel):
    rank: int
    user_id: str
    username: str
    is_you: bool = False
    score: float
    correct_count: int
    wrong_count: int
    unattempted_count: int
    time_taken_seconds: int
    submitted_at: datetime


class LeaderboardResponse(BaseModel):
    contest_id: str
    title: str
    total_participants: int
    your_rank: Optional[int] = None
    rows: list[LeaderboardRow]
