"""Internal value objects the pattern-mining pipeline reasons over.

These are deliberately separate from `schema.py` (the HTTP request/response
models) and `model.py` (the Mongo document factories) — same split the engine
uses with its `models.py`. Nothing here is serialised to the client directly.

    CleanedQuestion     — the HTML-stripped shape the agents actually see
    PatternSignature    — the structured trigger/technique the classifier compares
    Pattern             — a persisted pattern (one `patterns` row)
    PatternDraft        — what the namer returns BEFORE the pattern is written
    Stage1/Stage2/MatchOnly verdict — what each reducer agent returns
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class CleanedQuestion(BaseModel):
    """A raw `jee_mains_pyqs` doc after preprocessing.

    The raw document has HTML-wrapped fields, per-language nesting, and image
    flags; preprocessing strips all of that down to a clean text payload that
    fits in a Flash prompt. All text fields are HTML-stripped, math preserved.
    """

    model_config = ConfigDict(frozen=True)

    question_id: str
    subject: str
    chapter: str
    topic: str
    year: int
    difficulty: str

    question_text: str
    options_text: str          # "(A) ... (B) ... (C) ... (D) ..." or "" for integer
    answer_text: str           # correct option content, or numeric answer
    explanation_text: str      # full HTML-stripped explanation


class PatternSignature(BaseModel):
    """Structured handle on what makes the pattern recognisable.

    These three fields are what stage-1 / stage-2 / match-only reducers compare
    against. They MUST stay short — every pattern in a chunk gets serialised
    into the prompt, so brevity here is what keeps context costs sane.
    """

    model_config = ConfigDict(frozen=True)

    trigger: str = Field(..., description="What in the question makes you recognise this pattern (≤1 sentence).")
    technique: str = Field(..., description="The trick/method to apply (≤1 sentence).")
    why_it_works: str = Field(..., description="The underlying reason (≤1 sentence).")


class Pattern(BaseModel):
    """A persisted pattern. Unique on (chapter, slug)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    pattern_id: str                # opaque id (uuid4)
    chapter: str
    slug: str                       # url-safe id, e.g. "tan-inverse-sum-identity"
    name: str                       # human-readable, e.g. "Tan-inverse sum identity trick"
    description: str                # 2–4 sentences for a student
    signature: PatternSignature
    canonical_question_id: str      # the question that originally seeded this pattern
    member_count: int = 0
    prompt_version: str = "v1"
    created_at: datetime
    updated_at: Optional[datetime] = None


class PatternDraft(BaseModel):
    """What the namer agent returns before we hold the lock + write."""

    model_config = ConfigDict(frozen=True)

    slug: str
    name: str
    description: str
    signature: PatternSignature
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str


class Stage1Verdict(BaseModel):
    """One per chunk in the stage-1 fan-out."""

    model_config = ConfigDict(frozen=True)

    verdict: Literal["match", "none"]
    pattern_id: Optional[str] = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    evidence: str = ""


class Stage2Verdict(BaseModel):
    """The single winner-picker, run only when stage 1 produced 2+ matches."""

    model_config = ConfigDict(frozen=True)

    verdict: Literal["match", "none"]
    pattern_id: Optional[str] = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    evidence: str = ""


class MatchOnlyVerdict(BaseModel):
    """The cheap re-check that runs INSIDE the chapter lock before a new
    pattern is created."""

    model_config = ConfigDict(frozen=True)

    verdict: Literal["match", "none"]
    pattern_id: Optional[str] = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    evidence: str = ""
