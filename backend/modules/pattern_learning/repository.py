"""Motor I/O for pattern-learning.

Two repositories: one reads the mined catalog (adaptive_practice), the other
reads + writes per-student progress (pattern_learning DB). Both are handed their
database by the service (from modules.pattern_learning.db).
"""

from __future__ import annotations

from typing import Optional, Union

from motor.motor_asyncio import AsyncIOMotorDatabase

from modules.pattern_learning.constants import (
    ASSIGNMENTS_COLLECTION,
    ATTEMPTS_COLLECTION,
    PATTERNS_COLLECTION,
    QUESTIONS_COLLECTION,
)
from modules.pattern_learning.model import new_attempt_doc, now_utc


class CatalogRepository:
    """Read-only access to patterns / assignments / questions."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._patterns = db[PATTERNS_COLLECTION]
        self._assignments = db[ASSIGNMENTS_COLLECTION]
        self._questions = db[QUESTIONS_COLLECTION]

    async def chapters_with_patterns(self) -> list[str]:
        return [c for c in await self._patterns.distinct("chapter") if c]

    async def subject_by_chapter(self, chapters: list[str]) -> dict[str, str]:
        """Map each chapter slug → its subject (from the question catalog)."""
        if not chapters:
            return {}
        pipeline = [
            {"$match": {"chapter": {"$in": chapters}}},
            {"$group": {"_id": "$chapter", "subject": {"$first": "$subject"}}},
        ]
        out: dict[str, str] = {}
        async for r in self._questions.aggregate(pipeline):
            out[r["_id"]] = r.get("subject") or ""
        return out

    async def patterns_for_chapter(self, chapter: str) -> list[dict]:
        """Patterns in mining order (created_at asc) — the path sequence."""
        cursor = self._patterns.find({"chapter": chapter}).sort("created_at", 1)
        return [d async for d in cursor]

    async def get_pattern(self, pattern_id: str) -> Optional[dict]:
        return await self._patterns.find_one({"pattern_id": pattern_id})

    async def ordered_question_ids(self, pattern_id: str) -> list[str]:
        """Question ids for a pattern, in a stable path order."""
        cursor = self._assignments.find(
            {"pattern_id": pattern_id},
            {"question_id": 1, "created_at": 1, "_id": 0},
        ).sort([("created_at", 1), ("question_id", 1)])
        return [d["question_id"] async for d in cursor if d.get("question_id")]

    async def assignments_by_pattern(
        self, pattern_ids: list[str],
    ) -> dict[str, list[str]]:
        """{pattern_id: [question_ids in path order]} for many patterns at once."""
        if not pattern_ids:
            return {}
        cursor = self._assignments.find(
            {"pattern_id": {"$in": pattern_ids}},
            {"question_id": 1, "pattern_id": 1, "created_at": 1, "_id": 0},
        ).sort([("created_at", 1), ("question_id", 1)])
        out: dict[str, list[str]] = {}
        async for d in cursor:
            pid, qid = d.get("pattern_id"), d.get("question_id")
            if pid and qid:
                out.setdefault(pid, []).append(qid)
        return out

    async def pattern_id_for_question(self, question_id: str) -> Optional[str]:
        d = await self._assignments.find_one(
            {"question_id": question_id}, {"pattern_id": 1, "_id": 0},
        )
        return d.get("pattern_id") if d else None

    async def get_question(self, question_id: str) -> Optional[dict]:
        return await self._questions.find_one({"question_id": question_id})


class ProgressRepository:
    """Per-student attempt records (this module owns this collection)."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._attempts = db[ATTEMPTS_COLLECTION]

    async def record_attempt(
        self,
        *,
        user_id: str,
        chapter: str,
        pattern_id: str,
        question_id: str,
        user_answer: Union[str, list[str]],
        is_correct: bool,
    ) -> None:
        doc = new_attempt_doc(
            user_id=user_id, chapter=chapter, pattern_id=pattern_id,
            question_id=question_id, user_answer=user_answer, is_correct=is_correct,
        )
        await self._attempts.update_one(
            {"user_id": user_id, "question_id": question_id},
            {"$set": doc, "$setOnInsert": {"created_at": now_utc()}},
            upsert=True,
        )

    async def solved_in_chapter(self, user_id: str, chapter: str) -> set[str]:
        cursor = self._attempts.find(
            {"user_id": user_id, "chapter": chapter}, {"question_id": 1, "_id": 0},
        )
        return {d["question_id"] async for d in cursor if d.get("question_id")}

    async def solved_in_pattern(self, user_id: str, pattern_id: str) -> set[str]:
        cursor = self._attempts.find(
            {"user_id": user_id, "pattern_id": pattern_id}, {"question_id": 1, "_id": 0},
        )
        return {d["question_id"] async for d in cursor if d.get("question_id")}

    async def get_attempt(self, user_id: str, question_id: str) -> Optional[dict]:
        return await self._attempts.find_one(
            {"user_id": user_id, "question_id": question_id},
        )
