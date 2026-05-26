"""Request / response models for SolverX endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ComplexityMode = Literal["guided", "deep"]
ConversationMode = Literal["solve", "theory"]

QuestionText = Annotated[str, StringConstraints(min_length=1, max_length=20_000)]


# ---- requests ----

# A `data:image/...;base64,...` URL. Capped well below Groq's per-image
# limit so we fail fast on giant uploads instead of paying the round-trip.
ImageDataUrl = Annotated[str, StringConstraints(min_length=22, max_length=8_000_000)]


class SolveRequest(BaseModel):
    # When an image is attached, `question_text` can still hold the
    # student's caption / question framing. Allow it to be short — even
    # a single character — so the API doesn't reject "what's this?".
    question_text: Annotated[str, StringConstraints(min_length=1, max_length=20_000)] = "What is this?"
    image_data_url: Optional[ImageDataUrl] = None
    complexity_mode: ComplexityMode = "guided"
    conversation_id: Optional[str] = None


class TheoryRequest(BaseModel):
    question_text: Annotated[str, StringConstraints(min_length=1, max_length=20_000)] = "Explain what's in this image."
    image_data_url: Optional[ImageDataUrl] = None
    complexity_mode: ComplexityMode = "guided"
    conversation_id: Optional[str] = None


# ---- response (non-streaming list/detail endpoints) ----

class ConversationSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    mode: ConversationMode
    title: str
    last_message_preview: str = ""
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


class ConversationList(BaseModel):
    items: list[ConversationSummary]


class MessageBlock(BaseModel):
    """One structured block of a solution / explanation."""
    type: str
    title: Optional[str] = None
    content: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)


class TopicInfo(BaseModel):
    subject: Optional[str] = None
    chapter: Optional[str] = None
    topic: Optional[str] = None
    subtopic: Optional[str] = None
    difficulty: Optional[str] = None
    visual_needed: bool = False


class PersonalisedInsight(BaseModel):
    headline: str
    detail: str
    accuracy_pct: Optional[float] = None


class StoredMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    role: Literal["user", "assistant"]
    text: str = ""
    blocks: list[MessageBlock] = Field(default_factory=list)
    topic: Optional[TopicInfo] = None
    insights: list[PersonalisedInsight] = Field(default_factory=list)
    complexity_mode: Optional[ComplexityMode] = None
    created_at: datetime


class ConversationDetail(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    mode: ConversationMode
    title: str
    messages: list[StoredMessage]
    created_at: datetime
    updated_at: datetime
