"""Request / response models for the pattern-learning API."""

from __future__ import annotations

from typing import Optional, Union

from pydantic import BaseModel, Field


# ---- requests ----

class SubmitAnswerRequest(BaseModel):
    # mcq → "B"; mcqm → ["A", "C"]; integer → "42".
    answer: Union[str, list[str]]


# ---- subjects ----

class SubjectSummary(BaseModel):
    subject: str
    display_name: str
    chapter_count: int


class SubjectList(BaseModel):
    items: list[SubjectSummary]


# ---- chapters within a subject ----

class ChapterCard(BaseModel):
    chapter: str
    display_name: str
    pattern_count: int
    unlocked: bool            # is the chapter's first pattern open (gate cleared)?
    gate_accuracy: float      # the mock accuracy used for the gate
    gate_required: float      # threshold to clear
    completed_patterns: int


class ChapterList(BaseModel):
    subject: str
    display_name: str
    items: list[ChapterCard]


# ---- pattern roadmap (Duolingo path of patterns in a chapter) ----

class PatternNode(BaseModel):
    pattern_id: str
    name: str
    description: str
    sequence: int
    state: str                # locked | unlocked | completed
    solved_count: int
    total_count: int


class PatternRoadmap(BaseModel):
    chapter: str
    display_name: str
    unlocked: bool            # chapter gate cleared?
    gate_accuracy: float
    gate_required: float
    items: list[PatternNode]


# ---- question roadmap (Duolingo path of questions in a pattern) ----

class QuestionNode(BaseModel):
    question_id: str
    sequence: int
    state: str                # locked | unlocked | solved


class QuestionRoadmap(BaseModel):
    pattern_id: str
    pattern_name: str
    chapter: str
    unlocked: bool            # is the pattern itself unlocked?
    items: list[QuestionNode]


# ---- question content (for solving) ----

class QuestionOption(BaseModel):
    identifier: str
    content: str              # raw HTML + LaTeX (frontend renders math/images)
    is_image: bool = False


class QuestionContent(BaseModel):
    question_id: str
    pattern_id: str
    chapter: str
    type: str                 # mcq | mcqm | integer
    question_html: str        # raw HTML + LaTeX + <img>
    options: list[QuestionOption]
    # Revealed only once the student has submitted (any submission counts).
    answer_revealed: bool = False
    correct_options: list[str] = Field(default_factory=list)
    correct_value: Optional[str] = None
    explanation_html: Optional[str] = None
    prior_answer: Optional[Union[str, list[str]]] = None
    prior_correct: Optional[bool] = None


# ---- submit result ----

class SubmitResult(BaseModel):
    is_correct: bool
    correct_options: list[str] = Field(default_factory=list)
    correct_value: Optional[str] = None
    explanation_html: str = ""
    next_question_id: Optional[str] = None
    pattern_completed: bool = False
