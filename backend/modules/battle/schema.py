"""Pydantic request/response models for battle REST endpoints.

WebSocket message shapes are documented in `controller.py` and built as
plain dicts so they stay flexible — typing them as Pydantic would force
discriminated unions for very little payoff at this MVP stage.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class BattleOption(BaseModel):
    key: str
    text: str


class BattleQuestionPublic(BaseModel):
    """Answer-stripped question payload, the shape we send over the WS."""

    question_id: str
    index: int
    total: int
    question_text: str
    question_image: Optional[str] = None
    options: list[BattleOption]
    difficulty: str
    time_limit_seconds: float


class BattlePlayerSummary(BaseModel):
    user_id: str
    username: str
    score: int
    correct_count: int


class BattleHistoryItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    battle_id: str = Field(..., alias="_id")
    completed_at: datetime
    questions_count: int
    you: BattlePlayerSummary
    opponent: BattlePlayerSummary
    result: str  # "win" | "loss" | "draw"


class BattleHistoryResponse(BaseModel):
    items: list[BattleHistoryItem]


class BattleDetailResponse(BaseModel):
    battle_id: str
    completed_at: datetime
    questions_count: int
    you: BattlePlayerSummary
    opponent: BattlePlayerSummary
    result: str
    rounds: list["BattleRoundDetail"]


class BattleRoundDetail(BaseModel):
    index: int
    question_text: str
    options: list[BattleOption]
    correct_option: str
    your_answer: Optional[str]
    your_correct: bool
    your_score_delta: int
    opponent_answer: Optional[str]
    opponent_correct: bool
    opponent_score_delta: int


BattleDetailResponse.model_rebuild()
