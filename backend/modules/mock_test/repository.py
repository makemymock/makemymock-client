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
    NOTEBOOK_COLLECTION,
    PRACTICE_VIEWS_COLLECTION,
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
    new_notebook_entry_doc,
    new_practice_view_doc,
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
        self.practice_views = db[PRACTICE_VIEWS_COLLECTION]
        self.notebook = db[NOTEBOOK_COLLECTION]

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

    async def find_question_int_id(
        self, obj_id: str, sub_index: Optional[int] = None,
    ) -> Optional[int]:
        """Return the int id for a question/sub-question if one has been
        allocated, without creating one."""
        q: dict[str, Any] = {"obj_id": obj_id}
        q["sub_index"] = None if sub_index is None else int(sub_index)
        doc = await self.qid_map.find_one(q)
        return int(doc["_id"]) if doc else None

    async def view_times_for_obj_ids(
        self, user_id: ObjectId, obj_ids: Iterable[str],
    ) -> dict[str, Any]:
        """obj_id → last `viewed_at` for that user (missing keys = never viewed)."""
        ids = [o for o in obj_ids if o]
        if not ids:
            return {}
        out: dict[str, Any] = {}
        async for v in self.practice_views.find(
            {"user_id": user_id, "obj_id": {"$in": ids}},
            {"obj_id": 1, "viewed_at": 1},
        ):
            out[str(v["obj_id"])] = v.get("viewed_at")
        return out

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

    # ---------- browse (practice catalog) ----------
    # The Browse list expands a passage doc into one row per sub-question
    # (each sub becomes its own browseable card), so pagination has to count
    # post-expansion. Both helpers below run aggregation pipelines that
    # treat a passage as `N` rows where N = subQuestions length.

    def _browse_expansion_stages(self) -> list[dict]:
        """Stages that turn a `questions` match into one row per sub-question.

        After these stages, each pipeline doc has `_sub_index` (None for
        standalones, int for passage subs) and `_composite_key`
        ("{obj_id}" or "{obj_id}_{sub_index}") — usable in a follow-up
        `$match` to filter at sub-question granularity.
        """
        return [
            {"$addFields": {
                "_isPassage": {"$eq": [
                    {"$ifNull": ["$questionType", "single_correct"]}, "passage",
                ]},
            }},
            {"$addFields": {
                "_subRange": {
                    "$cond": [
                        "$_isPassage",
                        {"$range": [
                            0,
                            {"$size": {"$ifNull": ["$passageData.subQuestions", []]}},
                        ]},
                        [None],
                    ]
                }
            }},
            {"$unwind": "$_subRange"},
            {"$addFields": {
                "_sub_index": "$_subRange",
                "_composite_key": {
                    "$cond": [
                        {"$eq": ["$_subRange", None]},
                        {"$toString": "$_id"},
                        {"$concat": [
                            {"$toString": "$_id"}, "_",
                            {"$toString": "$_subRange"},
                        ]},
                    ]
                },
            }},
        ]

    async def count_browse(
        self, filt: dict, *, post_filter: Optional[dict] = None,
    ) -> int:
        pipeline: list[dict] = [{"$match": filt}]
        pipeline += self._browse_expansion_stages()
        if post_filter:
            pipeline.append({"$match": post_filter})
        pipeline.append({"$count": "total"})
        async for row in self.questions.aggregate(pipeline):
            return int(row.get("total") or 0)
        return 0

    async def find_browse(
        self,
        filt: dict,
        *,
        skip: int,
        limit: int,
        post_filter: Optional[dict] = None,
    ) -> list[dict]:
        """Paginated rows — one per standalone question and one per passage
        sub-question. Each row carries the original question doc fields plus
        `_sub_index` (None or int) and `_composite_key`.

        `post_filter` is applied after expansion, so callers can constrain
        by per-sub attributes (e.g., a specific set of composite keys)."""
        pipeline: list[dict] = [{"$match": filt}]
        pipeline += self._browse_expansion_stages()
        if post_filter:
            pipeline.append({"$match": post_filter})
        pipeline += [
            {"$sort": {"_id": 1, "_sub_index": 1}},
            {"$skip": max(0, skip)},
            {"$limit": max(1, limit)},
        ]
        return [doc async for doc in self.questions.aggregate(pipeline)]

    async def get_question_by_obj_id(self, obj_id: str) -> Optional[dict]:
        return await self.questions.find_one({"_id": ObjectId(obj_id)})

    async def qid_entries_for_obj_ids(
        self, obj_ids: Iterable[str],
    ) -> dict[str, list[dict]]:
        """Map each questions `_id` (str) → its `question_id_map` rows.

        A standalone question has one row (sub_index None); a passage has
        one row per sub-question (sub_index 0..n-1). Returns only obj_ids
        that have at least one allocated int id.
        """
        ids = [o for o in obj_ids if o]
        out: dict[str, list[dict]] = {}
        if not ids:
            return out
        async for doc in self.qid_map.find({"obj_id": {"$in": ids}}):
            out.setdefault(str(doc["obj_id"]), []).append(doc)
        return out

    async def attempts_for_int_ids(
        self, user_id: ObjectId, int_ids: Iterable[int],
    ) -> dict[int, dict]:
        ids = [int(i) for i in int_ids]
        out: dict[int, dict] = {}
        if not ids:
            return out
        cursor = self.attempts.find(
            {"user_id": user_id, "question_id": {"$in": ids}},
        )
        async for doc in cursor:
            out[int(doc["question_id"])] = doc
        return out

    async def attempted_composite_keys(self, user_id: ObjectId) -> set[str]:
        """All composite question keys the user has a genuine attempt on.

        Standalones map to `"{obj_id}"`; passage sub-Qs map to
        `"{obj_id}_{sub_index}"`. Walks attempts → int question_ids →
        qid_map rows so passage sub-attempts stay sub-precise rather than
        rolling up to the parent passage's obj_id.
        """
        int_ids: list[int] = []
        async for a in self.attempts.find(
            {"user_id": user_id}, {"question_id": 1},
        ):
            int_ids.append(int(a["question_id"]))
        if not int_ids:
            return set()
        id_to_doc = await self.bulk_lookup_question_int_to_obj(int_ids)
        out: set[str] = set()
        for d in id_to_doc.values():
            obj = d.get("obj_id")
            if not obj:
                continue
            sub = d.get("sub_index")
            out.add(str(obj) if sub is None else f"{obj}_{int(sub)}")
        return out

    # ---------- practice solution views ----------

    async def viewed_obj_ids(
        self, user_id: ObjectId, obj_ids: Optional[Iterable[str]] = None,
    ) -> set[str]:
        q: dict[str, Any] = {"user_id": user_id}
        if obj_ids is not None:
            ids = [o for o in obj_ids if o]
            if not ids:
                return set()
            q["obj_id"] = {"$in": ids}
        out: set[str] = set()
        async for doc in self.practice_views.find(q, {"obj_id": 1}):
            out.add(str(doc["obj_id"]))
        return out

    async def has_viewed(self, user_id: ObjectId, obj_id: str) -> bool:
        doc = await self.practice_views.find_one(
            {"user_id": user_id, "obj_id": obj_id}, {"_id": 1},
        )
        return doc is not None

    async def record_view(self, user_id: ObjectId, obj_id: str) -> None:
        await self.practice_views.update_one(
            {"user_id": user_id, "obj_id": obj_id},
            {"$setOnInsert": new_practice_view_doc(user_id=user_id, obj_id=obj_id)},
            upsert=True,
        )

    # ---------- notebook (revise-later) ----------

    async def add_to_notebook(self, user_id: ObjectId, obj_id: str) -> None:
        # Upsert keyed on (user, question) — idempotent, so marking a question
        # already in the notebook is a no-op (can't be added twice).
        await self.notebook.update_one(
            {"user_id": user_id, "obj_id": obj_id},
            {"$setOnInsert": new_notebook_entry_doc(user_id=user_id, obj_id=obj_id)},
            upsert=True,
        )

    async def remove_from_notebook(self, user_id: ObjectId, obj_id: str) -> None:
        await self.notebook.delete_one({"user_id": user_id, "obj_id": obj_id})

    async def is_in_notebook(self, user_id: ObjectId, obj_id: str) -> bool:
        doc = await self.notebook.find_one(
            {"user_id": user_id, "obj_id": obj_id}, {"_id": 1},
        )
        return doc is not None

    async def marked_obj_ids(
        self, user_id: ObjectId, obj_ids: Optional[Iterable[str]] = None,
    ) -> set[str]:
        q: dict[str, Any] = {"user_id": user_id}
        if obj_ids is not None:
            ids = [o for o in obj_ids if o]
            if not ids:
                return set()
            q["obj_id"] = {"$in": ids}
        out: set[str] = set()
        async for doc in self.notebook.find(q, {"obj_id": 1}):
            out.add(str(doc["obj_id"]))
        return out

    async def notebook_count(self, user_id: ObjectId) -> int:
        return await self.notebook.count_documents({"user_id": user_id})

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

    async def mark_attempt_non_feeding(
        self,
        *,
        user_id: ObjectId,
        question_id: int,
        topic_id: int,
        is_correct: bool,
        correctness: Optional[float],
        difficulty: str,
        attempted_at: Any,
        session_id: int,
    ) -> None:
        """Write a cooldown (non-feeding) attempt.

        Updates only the user-visible "latest attempt" fields and the
        cooldown clock — leaves the `e_*` engine-mirror fields untouched
        so a prior feeding attempt's signal stays authoritative for the
        recommender. If no row exists yet (first event was a solution
        view, then attempt within 24h), inserts a row with engine fields
        absent so engine queries skip it.
        """
        await self.attempts.update_one(
            {"user_id": user_id, "question_id": int(question_id)},
            {
                "$set": {
                    "is_correct": bool(is_correct),
                    "correctness": correctness,
                    "difficulty": difficulty,
                    "score_contribution": 0,
                    "attempted_at": attempted_at,
                    "session_id": int(session_id),
                    "last_event_at": attempted_at,
                },
                "$setOnInsert": {
                    "user_id": user_id,
                    "question_id": int(question_id),
                    "topic_id": int(topic_id),
                    # Mark the engine-mirror fields as explicitly empty
                    # so a recommender query (which filters on a non-null
                    # `e_attempted_at`) can tell a fresh cooldown-only
                    # row from a legacy pre-cooldown row.
                    "e_is_correct": None,
                    "e_correctness": None,
                    "e_difficulty": None,
                    "e_score_contribution": None,
                    "e_attempted_at": None,
                    "e_session_id": None,
                },
            },
            upsert=True,
        )

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
