"""Read-side business logic over the mined pattern catalog.

Thin by design: the heavy lifting (classification, dedupe) lives in the offline
`jobs/`. The service just shapes the persisted `patterns` / `pattern_assignments`
collections into the responses the controller returns. Maps the internal
`Pattern` value object onto the API dicts; never leaks Mongo `_id`s.
"""

from __future__ import annotations

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from modules.pattern_miner.domain import Pattern
from modules.pattern_miner.repository import (
    AssignmentRepository,
    PatternRepository,
)


def _pattern_summary(p: Pattern) -> dict:
    return {
        "pattern_id": p.pattern_id,
        "chapter": p.chapter,
        "slug": p.slug,
        "name": p.name,
        "description": p.description,
        "signature": {
            "trigger": p.signature.trigger,
            "technique": p.signature.technique,
            "why_it_works": p.signature.why_it_works,
        },
        "member_count": p.member_count,
    }


class PatternMinerService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.patterns = PatternRepository(db)
        self.assignments = AssignmentRepository(db)

    async def list_chapter_coverage(self) -> dict:
        """Every chapter that has at least one pattern, with its pattern count
        and how many questions those patterns cover."""
        return {"items": await self.patterns.chapter_coverage()}

    async def list_patterns_for_chapter(self, chapter: str) -> dict:
        """All patterns in a chapter, biggest bucket first."""
        patterns = await self.patterns.list_for_chapter(chapter)
        patterns.sort(key=lambda p: p.member_count, reverse=True)
        return {
            "chapter": chapter,
            "items": [_pattern_summary(p) for p in patterns],
        }

    async def get_pattern_detail(self, pattern_id: str) -> Optional[dict]:
        """One pattern plus the question_ids assigned to it. None if no such
        pattern exists."""
        pattern = await self.patterns.get_by_id(pattern_id)
        if pattern is None:
            return None
        question_ids = await self.assignments.question_ids_for_pattern(pattern_id)
        return {
            **_pattern_summary(pattern),
            "canonical_question_id": pattern.canonical_question_id,
            "question_ids": question_ids,
            "created_at": pattern.created_at,
            "updated_at": pattern.updated_at,
        }
