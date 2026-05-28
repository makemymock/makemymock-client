"""
MongoDB I/O layer for the JEE Recommender module.

Two responsibilities:
  1. CRUD operations on the five recommender collections.
  2. Agent tool query methods — small, filtered result sets for agents
     (§5.2: agents get tools, not raw data).

All methods are async and accept a Motor database instance. No business logic
lives here — only queries, projections, and aggregation pipelines.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, UpdateOne

from config.database import get_pyq_database
from modules.recommender.constants import (
    ERROR_CLUSTER_WINDOW,
    JEE_QUESTIONS_COLLECTION,
    MAX_CANDIDATE_QUESTIONS,
    MAX_FOCUS_TOPICS,
    PERSONALITY_COLLECTION,
    QUESTION_HISTORY_COLLECTION,
    SESSION_HISTORY_WINDOW,
    SESSION_SUMMARIES_COLLECTION,
    TOPIC_STATE_COLLECTION,
    TREND_HIGH_PRIORITY_THRESHOLD,
    TREND_SCORES_COLLECTION,
)
from modules.recommender.math_engine import ErrorTaxonomyComputer, PrerequisiteChecker
from modules.recommender.models import (
    new_question_history_doc,
    new_session_summary_doc,
    new_student_personality_doc,
    new_student_topic_state_doc,
    new_topic_trend_doc,
)

logger = logging.getLogger(__name__)

# Path to the prerequisite graph JSON: makemymock-client/prereqs_math.json
# __file__ = backend/modules/recommender/repository.py → go 4 levels up to makemymock-client/
_PREREQS_PATH = Path(__file__).parent.parent.parent.parent / "prereqs_math.json"


def _load_prereq_graph() -> dict[str, dict[str, Any]]:
    """Load the prerequisite dependency graph from prereqs_math.json."""
    with open(_PREREQS_PATH, encoding="utf-8") as f:
        return json.load(f)


# Module-level cache — loaded once on first call, never reloaded.
_PREREQ_GRAPH: dict[str, dict[str, Any]] | None = None


def get_prereq_graph() -> dict[str, dict[str, Any]]:
    """Return the cached prerequisite graph, loading it on first access."""
    global _PREREQ_GRAPH
    if _PREREQ_GRAPH is None:
        _PREREQ_GRAPH = _load_prereq_graph()
    return _PREREQ_GRAPH


# ---------------------------------------------------------------------------
# Student topic state CRUD
# ---------------------------------------------------------------------------

class RecommenderRepository:
    """
    All Motor I/O for the JEE Recommender, including agent tool query methods.

    Instantiated per-request with a Motor database (same pattern as other modules).
    The prereq_graph is loaded once at module level and shared across instances.
    """

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self._states = db[TOPIC_STATE_COLLECTION]
        self._personality = db[PERSONALITY_COLLECTION]
        self._history = db[QUESTION_HISTORY_COLLECTION]
        self._summaries = db[SESSION_SUMMARIES_COLLECTION]
        self._trends = db[TREND_SCORES_COLLECTION]
        # Questions live in adaptive_practice.jee_mains_pyqs on a separate Atlas
        # cluster — use the dedicated PYQ client (get_pyq_database()), falling back
        # to the main db only if the PYQ connection is not yet established.
        pyq_db = get_pyq_database()
        self._questions = (pyq_db if pyq_db is not None else db)[JEE_QUESTIONS_COLLECTION]

    # -----------------------------------------------------------------------
    # Initialization — creates 156 topic state docs from prereqs_math.json
    # -----------------------------------------------------------------------

    async def initialize_student(self, student_id: str) -> int:
        """
        Create one student_topic_state doc per topic in prereqs_math.json.

        Uses ordered=False bulk insert so a partial re-run (if some docs already
        exist due to a previous partial initialization) fails gracefully on
        duplicates without aborting the whole batch.

        Returns the count of newly inserted docs.
        """
        graph = get_prereq_graph()
        docs = [
            new_student_topic_state_doc(student_id, topic_id, node["chapter"])
            for topic_id, node in graph.items()
        ]
        if not docs:
            return 0
        try:
            result = await self._states.insert_many(docs, ordered=False)
            return len(result.inserted_ids)
        except Exception as exc:
            # BulkWriteError: some may already exist (duplicate key). Count successes.
            inserted = getattr(exc, "details", {}).get("nInserted", 0)
            logger.warning("Partial init for student %s: %d new, error: %s", student_id, inserted, exc)
            return inserted

    async def student_is_initialized(self, student_id: str) -> bool:
        """Return True if at least one topic state doc exists for this student."""
        doc = await self._states.find_one({"student_id": student_id}, {"_id": 1})
        return doc is not None

    # -----------------------------------------------------------------------
    # Topic state reads / writes
    # -----------------------------------------------------------------------

    async def get_topic_state(
        self, student_id: str, topic_id: str
    ) -> dict[str, Any] | None:
        """Fetch a single topic state document."""
        return await self._states.find_one(
            {"student_id": student_id, "topic_id": topic_id},
            {"_id": 0},
        )

    async def get_all_topic_states(
        self, student_id: str
    ) -> list[dict[str, Any]]:
        """Fetch all topic state documents for a student (156 docs)."""
        cursor = self._states.find(
            {"student_id": student_id}, {"_id": 0}
        )
        return await cursor.to_list(length=None)

    async def update_topic_state(
        self,
        student_id: str,
        topic_id: str,
        updates: dict[str, Any],
    ) -> None:
        """Partial update a topic state document with the given field values."""
        updates["updated_at"] = datetime.now(timezone.utc)
        await self._states.update_one(
            {"student_id": student_id, "topic_id": topic_id},
            {"$set": updates},
        )

    async def get_topic_states_dict(
        self, student_id: str
    ) -> dict[str, dict[str, Any]]:
        """Return all topic states keyed by topic_id for fast lookups."""
        docs = await self.get_all_topic_states(student_id)
        return {d["topic_id"]: d for d in docs}

    # -----------------------------------------------------------------------
    # Student personality
    # -----------------------------------------------------------------------

    async def create_personality(self, student_id: str) -> bool:
        """
        Create the default personality document for a new student.

        Returns False (without raising) if one already exists.
        """
        doc = new_student_personality_doc(student_id)
        try:
            await self._personality.insert_one(doc)
            return True
        except Exception:
            return False

    async def get_personality(self, student_id: str) -> dict[str, Any] | None:
        """Fetch the student personality document."""
        return await self._personality.find_one(
            {"student_id": student_id}, {"_id": 0}
        )

    async def update_personality(
        self, student_id: str, updates: dict[str, Any]
    ) -> None:
        """Partial update the personality document."""
        updates["updated_at"] = datetime.now(timezone.utc)
        await self._personality.update_one(
            {"student_id": student_id},
            {"$set": updates},
            upsert=True,
        )

    # -----------------------------------------------------------------------
    # Question history
    # -----------------------------------------------------------------------

    async def append_question_history(self, event: dict[str, Any]) -> None:
        """Insert one raw answer event into student_question_history."""
        await self._history.insert_one(event)

    async def get_recent_history(
        self, student_id: str, limit: int = ERROR_CLUSTER_WINDOW
    ) -> list[dict[str, Any]]:
        """Return the most recent `limit` answer events for a student."""
        cursor = self._history.find(
            {"student_id": student_id},
            {"_id": 0},
            sort=[("timestamp", DESCENDING)],
            limit=limit,
        )
        return await cursor.to_list(length=limit)

    async def get_seen_question_ids(
        self, student_id: str, topic_id: str
    ) -> list[str]:
        """Return question_ids the student has answered correctly in this topic."""
        cursor = self._history.find(
            {"student_id": student_id, "topic_id": topic_id, "correct": True},
            {"question_id": 1, "_id": 0},
        )
        docs = await cursor.to_list(length=None)
        return [d["question_id"] for d in docs]

    # -----------------------------------------------------------------------
    # Session summaries
    # -----------------------------------------------------------------------

    async def create_session_summary(self, doc: dict[str, Any]) -> str:
        """Insert a session summary and return its string id."""
        result = await self._summaries.insert_one(doc)
        return str(result.inserted_id)

    async def get_last_n_session_summaries(
        self, student_id: str, n: int = SESSION_HISTORY_WINDOW
    ) -> list[dict[str, Any]]:
        """Return the last N session summaries for a student, newest first."""
        cursor = self._summaries.find(
            {"student_id": student_id},
            {"_id": 0},
            sort=[("created_at", DESCENDING)],
            limit=n,
        )
        return await cursor.to_list(length=n)

    async def get_session_summary_by_id(
        self, session_id: str
    ) -> dict[str, Any] | None:
        """Fetch a specific session summary by session_id."""
        return await self._summaries.find_one(
            {"session_id": session_id}, {"_id": 0}
        )

    # -----------------------------------------------------------------------
    # Trend scores
    # -----------------------------------------------------------------------

    async def upsert_trend_score(self, doc: dict[str, Any]) -> None:
        """Upsert one topic trend score document (replace on topic_id match)."""
        await self._trends.replace_one(
            {"topic_id": doc["topic_id"]},
            doc,
            upsert=True,
        )

    async def get_all_trend_scores(self) -> list[dict[str, Any]]:
        """Return all topic trend score documents."""
        cursor = self._trends.find({}, {"_id": 0})
        return await cursor.to_list(length=None)

    async def get_trend_scores_dict(self) -> dict[str, float]:
        """Return a topic_id → p_appears mapping for Thompson Sampling."""
        docs = await self.get_all_trend_scores()
        return {d["topic_id"]: d["p_appears"] for d in docs}

    # -----------------------------------------------------------------------
    # Agent tool query methods (§5.2)
    # -----------------------------------------------------------------------

    async def tool_get_unlocked_topics(
        self, student_id: str
    ) -> list[dict[str, Any]]:
        """
        Return unlocked topics with mastery stats for the Session Planner.

        Filters topic states using the prerequisite graph and returns the top
        MAX_FOCUS_TOPICS by lowest mastery (highest urgency).
        """
        all_states = await self.get_topic_states_dict(student_id)
        graph = get_prereq_graph()
        trend_map = await self.get_trend_scores_dict()

        result = []
        for tid, state in all_states.items():
            if not PrerequisiteChecker.is_unlocked(tid, all_states, graph):
                continue
            alpha, beta_val = state["alpha"], state["beta"]
            mean = alpha / (alpha + beta_val)
            variance = (alpha * beta_val) / ((alpha + beta_val) ** 2 * (alpha + beta_val + 1))
            result.append({
                "topic_id": tid,
                "chapter": state["chapter"],
                "mastery_mean": round(mean, 3),
                "mastery_uncertainty": round(variance, 4),
                "p_appears_this_year": trend_map.get(tid, 0.5),
            })

        # Sort by mastery_mean ascending (weakest first)
        result.sort(key=lambda x: x["mastery_mean"])
        return result

    async def tool_get_due_reviews(
        self, student_id: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        """
        Return questions due for spaced-repetition review today.

        Queries student_topic_state for topics where next_review_date <= today,
        then picks one unseen question per due topic.
        """
        today = date.today().isoformat()
        cursor = self._states.find(
            {
                "student_id": student_id,
                "next_review_date": {"$lte": today},
                "total_attempts": {"$gt": 0},  # only topics with prior attempts
            },
            {"topic_id": 1, "chapter": 1, "next_review_date": 1, "_id": 0},
            limit=limit,
        )
        due_topics = await cursor.to_list(length=limit)

        result = []
        for t in due_topics:
            topic_id = t["topic_id"]
            today_date = date.today()
            try:
                review_date = date.fromisoformat(t["next_review_date"])
                overdue_days = (today_date - review_date).days
            except ValueError:
                overdue_days = 0

            # Find one seen question in this topic to serve as a review
            seen = await self._history.find_one(
                {"student_id": student_id, "topic_id": topic_id},
                {"question_id": 1, "_id": 0},
                sort=[("timestamp", DESCENDING)],
            )
            if seen:
                result.append({
                    "question_id": seen["question_id"],
                    "topic_id": topic_id,
                    "chapter": t.get("chapter", ""),
                    "overdue_days": max(0, overdue_days),
                })
        return result

    async def tool_get_weakest_unlocked(
        self, student_id: str, limit: int = MAX_FOCUS_TOPICS
    ) -> list[str]:
        """Return topic_ids of the weakest unlocked topics (lowest mastery_mean)."""
        unlocked = await self.tool_get_unlocked_topics(student_id)
        return [t["topic_id"] for t in unlocked[:limit]]

    async def tool_get_trend_top_topics(
        self, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Return the top-N topics by p_appears (exam-appearance probability)."""
        cursor = self._trends.find(
            {},
            {"topic_id": 1, "p_appears": 1, "chapter": 1, "_id": 0},
            sort=[("p_appears", DESCENDING)],
            limit=limit,
        )
        return await cursor.to_list(length=limit)

    async def tool_get_candidate_questions(
        self,
        topic_id: str,
        difficulty_min: float,
        difficulty_max: float,
        exclude_ids: list[str],
        limit: int = MAX_CANDIDATE_QUESTIONS,
    ) -> list[dict[str, Any]]:
        """
        Return candidate questions from jee_mains_pyqs for the Question Selector Agent.

        The pyqs collection uses `question_id` (string) as the document key, not
        MongoDB's `_id`. Excludes question_ids the student has already answered
        correctly this session. Returns minimal metadata for the agent to choose from.
        """
        chapter, topic = topic_id.split("::", 1) if "::" in topic_id else ("", topic_id)

        # Map IRT float difficulty band to catalog string values
        difficulty_filter = self._difficulty_band_filter(difficulty_min, difficulty_max)

        query: dict[str, Any] = {
            "chapter": chapter,
            "topic": topic,
            **difficulty_filter,
        }
        if exclude_ids:
            # jee_mains_pyqs uses question_id (string), not _id
            query["question_id"] = {"$nin": exclude_ids}

        cursor = self._questions.find(
            query,
            {
                "_id": 0,
                "question_id": 1,
                "difficulty": 1,
                "year": 1,
                "type": 1,
            },
            limit=limit,
        )
        docs = await cursor.to_list(length=limit)

        seen_set = set(exclude_ids)
        result = []
        for d in docs:
            qid = str(d.get("question_id", ""))
            if not qid:
                continue
            difficulty_str = d.get("difficulty", "medium")
            result.append({
                "question_id": qid,
                "difficulty": difficulty_str,
                "difficulty_float": self._difficulty_to_float(difficulty_str),
                "year": d.get("year", 0),
                "type": d.get("type", "single_correct"),
                "is_novel": qid not in seen_set,
            })
        return result

    async def tool_get_question_type_weights(
        self, student_id: str
    ) -> dict[str, float]:
        """
        Compute per-type improvement priority weights from attempt history.

        Weight is higher for types where the student performs worse, guiding
        the Question Selector to inject more of the student's weak type.
        """
        pipeline = [
            {"$match": {"student_id": student_id}},
            {
                "$group": {
                    "_id": "$question_type",
                    "total": {"$sum": 1},
                    "correct": {"$sum": {"$cond": ["$correct", 1, 0]}},
                }
            },
        ]
        cursor = self._history.aggregate(pipeline)
        docs = await cursor.to_list(length=None)

        type_accuracies: dict[str, float] = {}
        for d in docs:
            qtype = d["_id"] or "single_correct"
            total = d["total"]
            correct = d["correct"]
            type_accuracies[qtype] = correct / total if total > 0 else 0.5

        all_types = ["single_correct", "multi_correct", "integer", "matching"]
        for t in all_types:
            if t not in type_accuracies:
                type_accuracies[t] = 0.5

        # Weight = 1 - accuracy → lower accuracy = higher weight
        raw_weights = {t: 1.0 - type_accuracies[t] for t in all_types}
        total_w = sum(raw_weights.values()) or 1.0
        return {t: round(w / total_w, 3) for t, w in raw_weights.items()}

    async def tool_get_topic_attempt_stats(
        self, student_id: str, topic_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        """
        Return per-topic attempt statistics for the Diagnosis Agent.

        Computes: total_attempts, correct, avg_time_seconds, inconsistency_rate,
        difficulty_ceiling, time_z_score.
        """
        pipeline = [
            {"$match": {"student_id": student_id, "topic_id": {"$in": topic_ids}}},
            {
                "$group": {
                    "_id": "$topic_id",
                    "total": {"$sum": 1},
                    "correct": {"$sum": {"$cond": ["$correct", 1, 0]}},
                    "avg_time_ms": {"$avg": "$time_ms"},
                    "outcomes": {"$push": "$correct"},
                    "difficulties": {"$push": "$difficulty"},
                }
            },
        ]
        cursor = self._history.aggregate(pipeline)
        docs = await cursor.to_list(length=None)

        # Approximate population stats (use overall average as baseline)
        pop_stats = await self._get_population_time_stats()

        result: dict[str, dict[str, Any]] = {}
        for d in docs:
            tid = d["_id"]
            outcomes: list[bool] = d["outcomes"]
            difficulties: list[float] = [
                self._difficulty_to_float(x) if isinstance(x, str) else x
                for x in d["difficulties"]
            ]
            avg_ms = d["avg_time_ms"] or 0.0
            inconsistency = ErrorTaxonomyComputer.compute_inconsistency_rate(outcomes)
            ceiling = ErrorTaxonomyComputer.compute_difficulty_ceiling(difficulties, outcomes)
            pop_mean = pop_stats.get("mean_ms", avg_ms)
            pop_std = pop_stats.get("std_ms", 1.0)
            time_z = ErrorTaxonomyComputer.compute_time_z_score(avg_ms, pop_mean, pop_std)

            result[tid] = {
                "total_attempts": d["total"],
                "correct": d["correct"],
                "avg_time_seconds": round(avg_ms / 1000, 1),
                "inconsistency_rate": round(inconsistency, 3),
                "difficulty_ceiling": round(ceiling, 2),
                "time_z_score": round(time_z, 2),
            }
        return result

    async def tool_get_error_clusters(
        self, student_id: str, n_recent: int = ERROR_CLUSTER_WINDOW
    ) -> dict[str, dict[str, Any]]:
        """
        Classify dominant error type per topic from recent attempts.

        Returns { topic_id: { dominant_error_type, confidence } }.
        """
        history = await self.get_recent_history(student_id, limit=n_recent)

        # Group by topic
        by_topic: dict[str, list[dict[str, Any]]] = {}
        for event in history:
            tid = event.get("topic_id", "")
            by_topic.setdefault(tid, []).append(event)

        pop_stats = await self._get_population_time_stats()
        result: dict[str, dict[str, Any]] = {}

        for tid, events in by_topic.items():
            if len(events) < 3:
                continue
            outcomes = [e["correct"] for e in events]
            difficulties = [
                self._difficulty_to_float(e.get("difficulty", 0.0))
                if isinstance(e.get("difficulty"), str)
                else float(e.get("difficulty", 0.0))
                for e in events
            ]
            avg_ms = sum(e.get("time_ms", 0) for e in events) / len(events)
            inconsistency = ErrorTaxonomyComputer.compute_inconsistency_rate(outcomes)
            ceiling = ErrorTaxonomyComputer.compute_difficulty_ceiling(difficulties, outcomes)
            time_z = ErrorTaxonomyComputer.compute_time_z_score(
                avg_ms, pop_stats.get("mean_ms", avg_ms), pop_stats.get("std_ms", 1.0)
            )
            error_type = ErrorTaxonomyComputer.classify_error_type(
                inconsistency, ceiling, time_z
            )
            # Confidence: number of attempts / 10, capped at 1.0
            confidence = min(len(events) / 10.0, 1.0)
            result[tid] = {
                "dominant_error_type": error_type,
                "confidence": round(confidence, 2),
            }
        return result

    async def get_question_by_pyq_id(self, question_id: str) -> Optional[dict]:
        """Fetch a single PYQ document by its question_id string field."""
        return await self._questions.find_one({"question_id": question_id})

    async def get_student_stats(self, student_id: str) -> dict:
        """Aggregate total attempts, correct, mastery counts for the student."""
        pipeline = [
            {"$match": {"student_id": student_id}},
            {"$group": {
                "_id": None,
                "total_attempts": {"$sum": "$total_attempts"},
                "total_correct": {"$sum": "$total_correct"},
                "topics_attempted": {"$sum": {"$cond": [{"$gt": ["$total_attempts", 0]}, 1, 0]}},
                "topics_mastered": {"$sum": {"$cond": [{"$gte": ["$mastery_mean", 0.8]}, 1, 0]}},
                "unlocked_count": {"$sum": {"$cond": ["$is_unlocked", 1, 0]}},
            }},
        ]
        docs = await self._states.aggregate(pipeline).to_list(length=1)
        if not docs:
            return {"total_attempts": 0, "total_correct": 0, "topics_attempted": 0,
                    "topics_mastered": 0, "unlocked_count": 0}
        return docs[0]

    async def tool_get_topic_year_matrix(self) -> dict[str, dict[int, int]]:
        """
        Aggregate question counts by topic and year from the questions catalog.

        Returns { "chapter::topic": { year: count } } for all topics.
        """
        pipeline = [
            {
                "$group": {
                    "_id": {"chapter": "$chapter", "topic": "$topic", "year": "$year"},
                    "count": {"$sum": 1},
                }
            }
        ]
        cursor = self._questions.aggregate(pipeline)
        docs = await cursor.to_list(length=None)

        matrix: dict[str, dict[int, int]] = {}
        for d in docs:
            chapter = d["_id"].get("chapter", "")
            topic = d["_id"].get("topic", "")
            year = d["_id"].get("year")
            if not chapter or not topic or not year:
                continue
            topic_id = f"{chapter}::{topic}"
            matrix.setdefault(topic_id, {})[int(year)] = d["count"]
        return matrix

    async def tool_flag_prerequisite_gap(
        self, student_id: str, topic_id: str, gap_type: str
    ) -> None:
        """
        Append a prerequisite gap flag to the student's personality notes.

        gap_type: "conceptual_gap" | "needs_more_drill" | "avoidance_detected"
        """
        note = f"[{gap_type.upper()}] {topic_id}"
        await self._personality.update_one(
            {"student_id": student_id},
            {"$addToSet": {"avoidance_topics" if "avoidance" in gap_type else "persistent_weak_chapters": topic_id},
             "$set": {"updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        logger.info("Flagged %s for student %s: %s", gap_type, student_id, note)

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    async def _get_population_time_stats(self) -> dict[str, float]:
        """Compute mean and std of answer time_ms across all students (cached loosely)."""
        pipeline = [
            {
                "$group": {
                    "_id": None,
                    "mean": {"$avg": "$time_ms"},
                    "variance": {"$avg": {"$pow": [{"$subtract": ["$time_ms", {"$avg": "$time_ms"}]}, 2]}},
                }
            }
        ]
        # Use a simpler two-pass approximation
        pipeline = [
            {"$group": {"_id": None, "mean": {"$avg": "$time_ms"}, "count": {"$sum": 1}}}
        ]
        cursor = self._history.aggregate(pipeline)
        docs = await cursor.to_list(length=1)
        if not docs:
            return {"mean_ms": 60000.0, "std_ms": 30000.0}
        return {"mean_ms": docs[0].get("mean", 60000.0), "std_ms": 30000.0}

    @staticmethod
    def _difficulty_to_float(difficulty: str | float) -> float:
        """Convert difficulty string or float to IRT scale."""
        if isinstance(difficulty, (int, float)):
            return float(difficulty)
        mapping = {"easy": -1.0, "medium": 0.0, "hard": 1.0}
        return mapping.get(str(difficulty).lower(), 0.0)

    @staticmethod
    def _difficulty_band_filter(
        diff_min: float, diff_max: float
    ) -> dict[str, Any]:
        """
        Map IRT float difficulty range to catalog string filter.

        The catalog stores difficulty as "easy" / "medium" / "hard".
        We include all strings whose IRT float falls in [diff_min, diff_max].
        """
        candidates = []
        mapping = {"easy": -1.0, "medium": 0.0, "hard": 1.0}
        for label, val in mapping.items():
            if diff_min - 0.7 <= val <= diff_max + 0.7:
                candidates.append(label)
        if not candidates:
            candidates = ["medium"]
        return {"difficulty": {"$in": candidates}}
