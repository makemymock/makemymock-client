"""Read-side logic over the mined pattern catalog.

Shapes the persisted `patterns` / `pattern_assignments` documents into the API
responses the controller returns. Never writes; never leaks Mongo `_id`s.
"""

from __future__ import annotations

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from modules.pattern_miner.repository import PatternRepository


def _pattern_summary(d: dict) -> dict:
    sig = d.get("signature") or {}
    return {
        "pattern_id": d.get("pattern_id", ""),
        "chapter": d.get("chapter", ""),
        "slug": d.get("slug", ""),
        "name": d.get("name", ""),
        "description": d.get("description", ""),
        "signature": {
            "trigger": sig.get("trigger", ""),
            "technique": sig.get("technique", ""),
            "why_it_works": sig.get("why_it_works", ""),
        },
        "member_count": int(d.get("member_count", 0)),
    }


class PatternMinerService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.repo = PatternRepository(db)

    async def list_chapter_coverage(self) -> dict:
        """Every chapter that has at least one pattern, with its pattern count
        and how many questions those patterns cover."""
        return {"items": await self.repo.chapter_coverage()}

    async def list_patterns_for_chapter(self, chapter: str) -> dict:
        """All patterns in a chapter, biggest bucket first."""
        docs = await self.repo.list_for_chapter(chapter)
        return {"chapter": chapter, "items": [_pattern_summary(d) for d in docs]}

    async def get_pattern_detail(self, pattern_id: str) -> Optional[dict]:
        """One pattern plus the question_ids assigned to it. None if no such
        pattern exists."""
        doc = await self.repo.get_pattern(pattern_id)
        if doc is None:
            return None
        question_ids = await self.repo.question_ids_for_pattern(pattern_id)
        return {
            **_pattern_summary(doc),
            "canonical_question_id": doc.get("canonical_question_id", ""),
            "question_ids": question_ids,
            "created_at": doc.get("created_at"),
            "updated_at": doc.get("updated_at"),
        }
