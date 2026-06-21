"""Read-only Motor access to the mined pattern catalog.

The mining runs in the standalone Pattern_Miner pipeline, which writes
`patterns` + `pattern_assignments` to the PYQ cluster. This module only reads
them back, so the repository exposes lookups — never CRUD. Documents are
returned as raw dicts; the service shapes them into API responses.
"""

from __future__ import annotations

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from modules.pattern_miner.constants import (
    ASSIGNMENTS_COLLECTION,
    PATTERNS_COLLECTION,
)


class PatternRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._patterns = db[PATTERNS_COLLECTION]
        self._assignments = db[ASSIGNMENTS_COLLECTION]

    async def chapter_coverage(self) -> list[dict]:
        """Per-chapter rollup: how many patterns each chapter has, and how many
        question-memberships those patterns account for."""
        pipeline = [
            {
                "$group": {
                    "_id": "$chapter",
                    "pattern_count": {"$sum": 1},
                    "question_count": {"$sum": "$member_count"},
                }
            },
            {"$sort": {"_id": 1}},
        ]
        out: list[dict] = []
        async for row in self._patterns.aggregate(pipeline):
            out.append(
                {
                    "chapter": row["_id"],
                    "pattern_count": int(row.get("pattern_count", 0)),
                    "question_count": int(row.get("question_count", 0)),
                }
            )
        return out

    async def list_for_chapter(self, chapter: str) -> list[dict]:
        """All patterns in a chapter, biggest bucket first."""
        cursor = self._patterns.find({"chapter": chapter}).sort("member_count", -1)
        return [doc async for doc in cursor]

    async def get_pattern(self, pattern_id: str) -> Optional[dict]:
        return await self._patterns.find_one({"pattern_id": pattern_id})

    async def question_ids_for_pattern(self, pattern_id: str) -> list[str]:
        cursor = self._assignments.find(
            {"pattern_id": pattern_id}, {"question_id": 1, "_id": 0}
        )
        return [d["question_id"] async for d in cursor if d.get("question_id")]
