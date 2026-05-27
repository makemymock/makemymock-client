"""Mongo I/O for the mock-test module.

Owns the read-only catalog reads (questions collection, bbd_db schema) and
the read/write state collections (sessions, topics, responses, attempts).

All writes go through this layer; the engine never sees Motor.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument, UpdateOne

from modules.mock_test.constants import (
    ATTEMPTS_COLLECTION,
    CHAPTER_ID_MAP_COLLECTION,
    COUNTERS_COLLECTION,
    COUNTER_CHAPTER,
    COUNTER_QUESTION,
    COUNTER_SESSION,
    COUNTER_SUBJECT,
    COUNTER_TOPIC,
    QUESTIONS_COLLECTION,
    QUESTION_ID_MAP_COLLECTION,
    RESPONSES_COLLECTION,
    SESSIONS_COLLECTION,
    SUBJECT_ID_MAP_COLLECTION,
    TOPIC_ID_MAP_COLLECTION,
    TOPICS_COLLECTION,
)
from modules.mock_test.model import (
    new_attempt_doc,
    new_response_doc,
    new_session_doc,
    new_topic_allocation_doc,
    now_utc,
)

class MockTestRepository:
    """Wraps every Mongo collection the mock-test feature touches.

    Methods are async (Motor); the engine never calls these directly — the
    service builds a `BufferedRepository` and shuttles data in/out.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.questions = db[QUESTIONS_COLLECTION]
        self.sessions = db[SESSIONS_COLLECTION]
        self.topics_col = db[TOPICS_COLLECTION]
        self.responses = db[RESPONSES_COLLECTION]
        self.attempts = db[ATTEMPTS_COLLECTION]
        self.counters = db[COUNTERS_COLLECTION]
        self.qid_map = db[QUESTION_ID_MAP_COLLECTION]
        self.topic_map = db[TOPIC_ID_MAP_COLLECTION]
        self.chapter_map = db[CHAPTER_ID_MAP_COLLECTION]
        self.subject_map = db[SUBJECT_ID_MAP_COLLECTION]

    # ---------- counters ----------

    async def next_id(self, counter_id: str) -> int:
        doc = await self.counters.find_one_and_update(
            {"_id": counter_id},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return int(doc["seq"])

    # ---------- subject/chapter/topic id maps ----------

    async def get_or_create_subject_id(self, subject: str) -> int:
        existing = await self.subject_map.find_one({"name": subject})
        if existing is not None:
            return int(existing["_id"])
        new_id = await self.next_id(COUNTER_SUBJECT)
        try:
            await self.subject_map.insert_one({"_id": new_id, "name": subject})
        except Exception:
            re_check = await self.subject_map.find_one({"name": subject})
            if re_check is not None:
                return int(re_check["_id"])
            raise
        return new_id

    async def get_or_create_chapter_id(self, subject_id: int, name: str) -> int:
        existing = await self.chapter_map.find_one(
            {"subject_id": subject_id, "name": name},
        )
        if existing is not None:
            return int(existing["_id"])
        new_id = await self.next_id(COUNTER_CHAPTER)
        try:
            await self.chapter_map.insert_one(
                {"_id": new_id, "subject_id": subject_id, "name": name},
            )
        except Exception:
            re_check = await self.chapter_map.find_one(
                {"subject_id": subject_id, "name": name},
            )
            if re_check is not None:
                return int(re_check["_id"])
            raise
        return new_id

    async def get_or_create_topic_id(
        self, subject: str, chapter: str, topic: str,
    ) -> tuple[int, int, int]:
        """Return (subject_id, chapter_id, topic_id) — creating any missing."""
        sid = await self.get_or_create_subject_id(subject)
        cid = await self.get_or_create_chapter_id(sid, chapter)
        existing = await self.topic_map.find_one(
            {"chapter_id": cid, "name": topic},
        )
        if existing is not None:
            return sid, cid, int(existing["_id"])
        new_id = await self.next_id(COUNTER_TOPIC)
        try:
            await self.topic_map.insert_one(
                {"_id": new_id, "chapter_id": cid, "subject_id": sid,
                 "name": topic, "subject": subject, "chapter": chapter},
            )
        except Exception:
            re_check = await self.topic_map.find_one(
                {"chapter_id": cid, "name": topic},
            )
            if re_check is not None:
                return sid, cid, int(re_check["_id"])
            raise
        return sid, cid, new_id

    async def lookup_topic_triple(
        self, topic_id: int,
    ) -> Optional[tuple[str, str, str]]:
        doc = await self.topic_map.find_one({"_id": int(topic_id)})
        if doc is None:
            return None
        return (doc.get("subject", ""), doc.get("chapter", ""), doc.get("name", ""))

    async def lookup_topic_chapter_id(self, topic_id: int) -> Optional[int]:
        doc = await self.topic_map.find_one({"_id": int(topic_id)})
        if doc is None:
            return None
        return int(doc["chapter_id"])

    async def topic_chapter_map(
        self, topic_ids: Iterable[int],
    ) -> dict[int, int]:
        tids = [int(t) for t in topic_ids]
        result: dict[int, int] = {}
        if not tids:
            return result
        cursor = self.topic_map.find({"_id": {"$in": tids}})
        async for doc in cursor:
            result[int(doc["_id"])] = int(doc["chapter_id"])
        return result

    # ---------- question id map ----------

    async def get_or_create_question_int_id(
        self, obj_id: str, sub_index: Optional[int] = None,
    ) -> int:
        """Allocate a stable int id for a question or sub-question."""
        if sub_index is None:
            existing = await self.qid_map.find_one(
                {"obj_id": obj_id, "sub_index": None},
            )
        else:
            existing = await self.qid_map.find_one(
                {"obj_id": obj_id, "sub_index": int(sub_index)},
            )
        if existing is not None:
            return int(existing["_id"])
        new_id = await self.next_id(COUNTER_QUESTION)
        doc = {
            "_id": new_id,
            "obj_id": obj_id,
            "sub_index": (None if sub_index is None else int(sub_index)),
        }
        try:
            await self.qid_map.insert_one(doc)
        except Exception:
            re_check = await self.qid_map.find_one(
                {"obj_id": obj_id, "sub_index": doc["sub_index"]},
            )
            if re_check is not None:
                return int(re_check["_id"])
            raise
        return new_id

    async def lookup_question_int(self, int_id: int) -> Optional[dict]:
        return await self.qid_map.find_one({"_id": int(int_id)})

    async def bulk_lookup_question_int_to_obj(
        self, int_ids: Iterable[int],
    ) -> dict[int, dict]:
        ids = [int(i) for i in int_ids]
        if not ids:
            return {}
        out: dict[int, dict] = {}
        async for doc in self.qid_map.find({"_id": {"$in": ids}}):
            out[int(doc["_id"])] = doc
        return out

    # ---------- catalog reads (questions collection) ----------

    async def fetch_questions_for_triples(
        self, triples: list[tuple[str, str, str]],
    ) -> list[dict]:
        if not triples:
            return []
        or_clauses = [
            {"subject": s, "chapter": c, "topic": t}
            for (s, c, t) in triples
        ]
        cursor = self.questions.find({"$or": or_clauses}).sort("_id", 1)
        return [doc async for doc in cursor]

    async def fetch_question_docs_by_obj_ids(
        self, obj_ids: Iterable[str],
    ) -> dict[str, dict]:
        ids = [ObjectId(o) for o in obj_ids if o]
        if not ids:
            return {}
        out: dict[str, dict] = {}
        cursor = self.questions.find({"_id": {"$in": ids}})
        async for doc in cursor:
            out[str(doc["_id"])] = doc
        return out

    async def list_all_catalog_topics(self) -> dict[str, Any]:
        """Aggregate the questions collection into a subject→chapter→topic
        tree with question counts."""
        pipeline = [
            {"$project": {
                "subject": 1, "chapter": 1, "topic": 1,
                "questionType": 1,
                "subCount": {
                    "$cond": [
                        {"$eq": [{"$ifNull": ["$questionType", "single_correct"]}, "passage"]},
                        {"$size": {"$ifNull": ["$passageData.subQuestions", []]}},
                        1,
                    ]
                },
            }},
            {"$group": {
                "_id": {
                    "subject": "$subject",
                    "chapter": "$chapter",
                    "topic": "$topic",
                },
                "question_count": {"$sum": "$subCount"},
            }},
        ]
        results = []
        async for row in self.questions.aggregate(pipeline):
            key = row["_id"]
            results.append({
                "subject": (key.get("subject") or "Uncategorized").strip(),
                "chapter": (key.get("chapter") or "Uncategorized").strip(),
                "topic": (key.get("topic") or "Uncategorized").strip(),
                "question_count": int(row["question_count"]),
            })
        return results

    # ---------- session writes ----------

    async def create_session_doc(
        self,
        session_id: int,
        user_id: ObjectId,
        total_questions: int,
        extra_questions: int,
        total_seconds: int,
        topic_ids: list[int],
    ) -> dict:
        doc = new_session_doc(
            session_id=session_id, user_id=user_id,
            total_questions=total_questions, extra_questions=extra_questions,
            total_seconds=total_seconds, topic_ids=topic_ids,
        )
        await self.sessions.insert_one(doc)
        return doc

    async def insert_topic_allocations(
        self, session_id: int,
        rows: list[dict],
    ) -> None:
        if not rows:
            return
        await self.topics_col.insert_many(rows)

    async def insert_response_rows(self, rows: list[dict]) -> None:
        if not rows:
            return
        await self.responses.insert_many(rows)

    async def update_session_status(
        self,
        session_id: int,
        *,
        status: str,
        score: float,
        correct: int,
        incorrect: int,
        partial: int,
    ) -> None:
        await self.sessions.update_one(
            {"_id": session_id},
            {"$set": {
                "status": status,
                "completed_at": now_utc(),
                "score": float(score),
                "correct": int(correct),
                "incorrect": int(incorrect),
                "partial": int(partial),
            }},
        )

    async def update_response_grading(
        self,
        session_id: int,
        question_id: int,
        user_answer: Any,
        is_correct: bool,
        correctness: Optional[float],
    ) -> None:
        await self.responses.update_one(
            {"session_id": session_id, "question_id": question_id},
            {"$set": {
                "user_answer": user_answer,
                "is_correct": bool(is_correct),
                "correctness": correctness,
                "answered_at": now_utc(),
            }},
        )

    async def bulk_upsert_attempts(self, attempt_docs: list[dict]) -> None:
        if not attempt_docs:
            return
        ops = []
        for d in attempt_docs:
            ops.append(UpdateOne(
                {"user_id": d["user_id"], "question_id": d["question_id"]},
                {"$set": d},
                upsert=True,
            ))
        await self.attempts.bulk_write(ops, ordered=False)

    # ---------- session reads ----------

    async def get_session(
        self, session_id: int, user_id: ObjectId,
    ) -> Optional[dict]:
        return await self.sessions.find_one(
            {"_id": int(session_id), "user_id": user_id},
        )

    async def get_responses_for_session(
        self, session_id: int,
    ) -> list[dict]:
        cursor = self.responses.find({"session_id": int(session_id)}).sort(
            "display_order", 1,
        )
        return [doc async for doc in cursor]

    async def get_topic_allocations_for_session(
        self, session_id: int,
    ) -> list[dict]:
        cursor = self.topics_col.find({"session_id": int(session_id)})
        return [doc async for doc in cursor]

    # ---------- analytics reads ----------

    async def list_user_sessions(
        self, user_id: ObjectId, limit: int = 50,
    ) -> list[dict]:
        cursor = self.sessions.find({"user_id": user_id}).sort(
            "created_at", -1,
        ).limit(limit)
        return [doc async for doc in cursor]

    async def list_user_attempts(
        self, user_id: ObjectId,
    ) -> list[dict]:
        cursor = self.attempts.find({"user_id": user_id})
        return [doc async for doc in cursor]

    # ---------- analytics aggregations ----------

    async def list_topic_allocations_for_user(
        self, user_id: ObjectId,
    ) -> list[dict]:
        """Every (session_id, topic_id) allocation row across the user's
        completed sessions, with the session's `completed_at` joined in.

        Used to reconstruct priority-score-over-time per topic/chapter.
        """
        pipeline = [
            {"$lookup": {
                "from": SESSIONS_COLLECTION,
                "localField": "session_id",
                "foreignField": "_id",
                "as": "session",
            }},
            {"$unwind": "$session"},
            {"$match": {
                "session.user_id": user_id,
                "session.status": "completed",
            }},
            {"$project": {
                "_id": 0,
                "session_id": "$session_id",
                "topic_id": "$topic_id",
                "question_count": "$question_count",
                "priority_score": "$priority_score",
                "decay_factor": "$decay_factor",
                "completed_at": "$session.completed_at",
                "created_at": "$session.created_at",
            }},
            {"$sort": {"completed_at": 1}},
        ]
        cursor = self.topics_col.aggregate(pipeline)
        return [doc async for doc in cursor]

    async def list_all_topics_grouped_by_chapter(self) -> dict[int, list[dict]]:
        """All catalog topics keyed by chapter_id. Used to compute
        attempted_topic_count vs total_topic_count."""
        cursor = self.topic_map.find({})
        out: dict[int, list[dict]] = {}
        async for doc in cursor:
            cid = int(doc.get("chapter_id", 0))
            out.setdefault(cid, []).append(doc)
        return out

    async def get_chapter_doc(self, chapter_id: int) -> Optional[dict]:
        return await self.chapter_map.find_one({"_id": int(chapter_id)})

    async def get_topic_doc(self, topic_id: int) -> Optional[dict]:
        return await self.topic_map.find_one({"_id": int(topic_id)})

    async def get_subject_doc(self, subject_id: int) -> Optional[dict]:
        return await self.subject_map.find_one({"_id": int(subject_id)})

    async def list_topics_for_chapter(self, chapter_id: int) -> list[dict]:
        cursor = self.topic_map.find({"chapter_id": int(chapter_id)})
        return [doc async for doc in cursor]
