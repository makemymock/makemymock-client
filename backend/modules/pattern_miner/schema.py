"""Request / response models for the pattern-miner read API.

The mining itself runs offline (see `jobs/`); these models only describe the
catalog the mining produced, read back over HTTP.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PatternSignatureOut(BaseModel):
    trigger: str
    technique: str
    why_it_works: str


class PatternSummary(BaseModel):
    pattern_id: str
    chapter: str
    slug: str
    name: str
    description: str
    signature: PatternSignatureOut
    member_count: int


class PatternList(BaseModel):
    chapter: str
    items: list[PatternSummary]


class ChapterCoverage(BaseModel):
    chapter: str
    pattern_count: int
    # Total question-memberships across this chapter's patterns — i.e. how many
    # PYQs the catalog covers here.
    question_count: int


class ChapterCoverageList(BaseModel):
    items: list[ChapterCoverage]


class PatternDetail(PatternSummary):
    canonical_question_id: str
    question_ids: list[str]
    created_at: datetime
    updated_at: Optional[datetime] = None
