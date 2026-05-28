"""Pydantic request/response models for POTD endpoints."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Question shape — a minimal projection of the question the user sees.
# Answers + worked solution are never on this object; they come back through
# the attempt / view-solution endpoints.
# ---------------------------------------------------------------------------

class PotdOption(BaseModel):
    key: str
    text: str


class PotdQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str                 # ObjectId as string
    topic_id: int
    topic_name: Optional[str] = None
    subject: Optional[str] = None
    chapter: Optional[str] = None
    difficulty: str
    question_type: str
    question_text: str = ""
    options: list[PotdOption] = Field(default_factory=list)
    # `matching` projects two columns; integer / single / multi don't use them.
    left_column: list[str] = Field(default_factory=list)
    right_column: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Today's POTD — what the modal opens on.
# ---------------------------------------------------------------------------

PotdStatus = Literal["in_progress", "solved", "viewed", "exhausted"]


class TodayResponse(BaseModel):
    date_ist: str                    # YYYY-MM-DD
    question: PotdQuestion
    status: PotdStatus
    attempt_count: int
    max_attempts: Optional[int]      # set for single_correct; None for others
    # Populated only when status is solved / viewed / exhausted — at that
    # point the modal renders a result view, so the answer + solution can
    # legitimately ride along on the initial fetch.
    correct_answer: Any = None
    solution: Optional[str] = None
    first_correct_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Attempt — submitted answer for today's POTD.
# ---------------------------------------------------------------------------

class AttemptRequest(BaseModel):
    selected_option: Optional[str] = None
    selected_options: Optional[list[str]] = None
    integer_answer: Optional[Any] = None
    matching: Optional[dict[str, list[str]]] = None


class AttemptResponse(BaseModel):
    correct: bool
    status: PotdStatus
    attempt_count: int
    max_attempts: Optional[int]
    # Populated on the final reveal: correct attempt, or single_correct
    # exhaustion. Wrong attempts (with retries left) leave both as None.
    correct_answer: Any = None
    solution: Optional[str] = None
    # Updated streak counters so the chip / banner can refresh without a
    # second round-trip.
    streak_after: int


# ---------------------------------------------------------------------------
# Solution-view — explicit "give up" path.
# ---------------------------------------------------------------------------

class ViewSolutionResponse(BaseModel):
    solution: str = ""
    correct_answer: Any = None
    streak_after: int                # 0 — the day's status becomes "viewed"


# ---------------------------------------------------------------------------
# Streak chip data.
# ---------------------------------------------------------------------------

class StreakResponse(BaseModel):
    current: int                     # consecutive solved days ending today (or yesterday)
    longest: int                     # all-time
    last_solved_at: Optional[date] = None


# ---------------------------------------------------------------------------
# Calendar — last N days; one row per IST date the user engaged with POTD.
# Missing dates are inferred as "missed" on the client.
# ---------------------------------------------------------------------------

class HistoryDay(BaseModel):
    date_ist: str
    status: PotdStatus
    question_id: str
    attempt_count: int


class HistoryResponse(BaseModel):
    days: list[HistoryDay] = Field(default_factory=list)
    range_days: int


# ---------------------------------------------------------------------------
# Past-date detail — clicking a calendar cell.
# ---------------------------------------------------------------------------

class PastAttemptInfo(BaseModel):
    attempt_n: int
    correct: bool
    attempted_at: datetime


class PastDateResponse(BaseModel):
    date_ist: str
    question: PotdQuestion
    status: PotdStatus
    attempt_count: int
    correct_answer: Any = None
    solution: Optional[str] = None
    user_last_answer: Any = None
    user_last_correct: Optional[bool] = None
