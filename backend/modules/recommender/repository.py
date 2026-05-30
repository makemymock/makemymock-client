from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, UpdateOne

from config.database import get_pyq_database
from modules.recommender.constants import (
    ATTEMPTED_EXCLUSION_DAYS,
    ERROR_CLUSTER_WINDOW,
    INCORRECT_FIRST_INTERVAL_DAYS,
    INCORRECT_MAX_INTERVAL_DAYS,
    JEE_QUESTIONS_COLLECTION,
    MAX_CANDIDATE_QUESTIONS,
    MAX_FOCUS_TOPICS,
    PERSONALITY_COLLECTION,
    QUESTION_HISTORY_COLLECTION,
    SESSION_HISTORY_WINDOW,
    SESSION_SUMMARIES_COLLECTION,
    SOLVED_QUESTIONS_COLLECTION,
    SUBJECT_MATHEMATICS,
    TOPIC_STATE_COLLECTION,
    TREND_HIGH_PRIORITY_THRESHOLD,
    TREND_SCORES_COLLECTION,
)
from modules.recommender.math_engine import ErrorTaxonomyComputer, PrerequisiteChecker
from modules.recommender.models import (
    new_solved_question_doc,
    new_student_personality_doc,
    new_student_topic_state_doc,
)

logger = logging.getLogger(__name__)

_PREREQS_PATH = Path(__file__).parent.parent.parent.parent / "prereqs_math.json"
_PREREQ_GRAPH: dict | None = None


def get_prereq_graph() -> dict:
    global _PREREQ_GRAPH
    if _PREREQ_GRAPH is None:
        with open(_PREREQS_PATH, encoding="utf-8") as f:
            _PREREQ_GRAPH = json.load(f)
    return _PREREQ_GRAPH


class RecommenderRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db          = db
        self._states      = db[TOPIC_STATE_COLLECTION]
        self._personality = db[PERSONALITY_COLLECTION]
        self._history     = db[QUESTION_HISTORY_COLLECTION]
        self._summaries   = db[SESSION_SUMMARIES_COLLECTION]
        self._trends      = db[TREND_SCORES_COLLECTION]
        self._solved      = db[SOLVED_QUESTIONS_COLLECTION]
        pyq_db = get_pyq_database()
        self._questions = (pyq_db if pyq_db is not None else db)[JEE_QUESTIONS_COLLECTION]

    # --- initialization ---

    async def initialize_student(self, student_id: str) -> int:
        graph = get_prereq_graph()
        docs  = [
            new_student_topic_state_doc(student_id, topic_id, node["chapter"], subject=SUBJECT_MATHEMATICS)
            for topic_id, node in graph.items()
        ]
        if not docs: return 0
        try:
            result = await self._states.insert_many(docs, ordered=False)
            return len(result.inserted_ids)
        except Exception as exc:
            inserted = getattr(exc, "details", {}).get("nInserted", 0)
            logger.warning("Partial init for %s: %d new, error: %s", student_id, inserted, exc)
            return inserted

    async def student_is_initialized(self, student_id: str) -> bool:
        return await self._states.find_one({"student_id": student_id}, {"_id": 1}) is not None

    # --- topic states ---

    async def get_topic_state(self, student_id: str, topic_id: str) -> dict | None:
        return await self._states.find_one({"student_id": student_id, "topic_id": topic_id}, {"_id": 0})

    async def get_all_topic_states(self, student_id: str) -> list[dict]:
        return await self._states.find({"student_id": student_id}, {"_id": 0}).to_list(length=None)

    async def get_topic_states_dict(self, student_id: str) -> dict[str, dict]:
        docs = await self.get_all_topic_states(student_id)
        return {d["topic_id"]: d for d in docs}

    async def update_topic_state(self, student_id: str, topic_id: str, updates: dict) -> None:
        updates["updated_at"] = datetime.now(timezone.utc)
        await self._states.update_one({"student_id": student_id, "topic_id": topic_id}, {"$set": updates})

    # --- personality ---

    async def create_personality(self, student_id: str) -> bool:
        try:
            await self._personality.insert_one(new_student_personality_doc(student_id))
            return True
        except Exception:
            return False

    async def get_personality(self, student_id: str) -> dict | None:
        return await self._personality.find_one({"student_id": student_id}, {"_id": 0})

    async def update_personality(self, student_id: str, updates: dict) -> None:
        updates["updated_at"] = datetime.now(timezone.utc)
        await self._personality.update_one({"student_id": student_id}, {"$set": updates}, upsert=True)

    # --- question history ---

    async def append_question_history(self, event: dict) -> None:
        await self._history.insert_one(event)

    async def get_recent_history(self, student_id: str, limit: int = ERROR_CLUSTER_WINDOW) -> list[dict]:
        return await self._history.find(
            {"student_id": student_id}, {"_id": 0},
            sort=[("timestamp", DESCENDING)], limit=limit,
        ).to_list(length=limit)

    async def get_seen_question_ids(self, student_id: str, topic_id: str) -> list[str]:
        docs = await self._history.find(
            {"student_id": student_id, "topic_id": topic_id, "correct": True},
            {"question_id": 1, "_id": 0},
        ).to_list(length=None)
        return [d["question_id"] for d in docs]

    # --- session summaries ---

    async def create_session_summary(self, doc: dict) -> str:
        result = await self._summaries.insert_one(doc)
        return str(result.inserted_id)

    async def get_last_n_session_summaries(self, student_id: str, n: int = SESSION_HISTORY_WINDOW) -> list[dict]:
        return await self._summaries.find(
            {"student_id": student_id}, {"_id": 0},
            sort=[("created_at", DESCENDING)], limit=n,
        ).to_list(length=n)

    async def get_session_summary_by_id(self, session_id: str) -> dict | None:
        return await self._summaries.find_one({"session_id": session_id}, {"_id": 0})

    # --- trend scores ---

    async def upsert_trend_score(self, doc: dict) -> None:
        await self._trends.replace_one({"topic_id": doc["topic_id"]}, doc, upsert=True)

    async def get_all_trend_scores(self) -> list[dict]:
        return await self._trends.find({}, {"_id": 0}).to_list(length=None)

    async def get_trend_scores_dict(self) -> dict[str, float]:
        docs = await self.get_all_trend_scores()
        return {d["topic_id"]: d["p_appears"] for d in docs}

    # --- solved questions (per-question SM-2) ---

    async def upsert_solved_question(
        self, student_id: str, question_id: str, topic_id: str,
        chapter: str, difficulty: float, question_type: str,
        last_correct: bool = True,
        subject: str = SUBJECT_MATHEMATICS,
    ) -> None:
        existing = await self._solved.find_one(
            {"student_id": student_id, "question_id": question_id}, {"_id": 0}
        )
        if existing is None:
            doc = new_solved_question_doc(
                student_id, question_id, topic_id, chapter,
                difficulty, question_type, last_correct=last_correct, subject=subject,
            )
            await self._solved.insert_one(doc)
        else:
            times_attempted = existing.get("times_attempted", existing.get("times_solved", 1)) + 1
            times_correct   = existing.get("times_correct", 1 if existing.get("last_correct", True) else 0)
            consec_wrong    = existing.get("consecutive_incorrect", 0)

            if last_correct:
                # SM-2: lengthen interval
                ef       = float(existing.get("easiness_factor", 2.5))
                interval = max(1, round(existing.get("review_interval_days", 1) * ef))
                times_correct  += 1
                consec_wrong    = 0
            else:
                # Incorrect: short interval capped at INCORRECT_MAX_INTERVAL_DAYS
                consec_wrong += 1
                interval = min(
                    INCORRECT_MAX_INTERVAL_DAYS,
                    max(INCORRECT_FIRST_INTERVAL_DAYS, existing.get("review_interval_days", 1)),
                )

            next_rev = (date.today() + timedelta(days=interval)).isoformat()
            await self._solved.update_one(
                {"student_id": student_id, "question_id": question_id},
                {"$set": {
                    "last_correct": last_correct,
                    "times_attempted": times_attempted,
                    "times_correct": times_correct,
                    "consecutive_incorrect": consec_wrong,
                    "last_attempted_at": datetime.now(timezone.utc),
                    "review_interval_days": interval,
                    "next_review_date": next_rev,
                    "subject": subject,
                }}
            )

    async def get_solved_not_due_ids(self, student_id: str) -> set[str]:
        """All attempted question IDs (correct OR incorrect) whose next_review_date is still
        in the future — excluded from the normal candidate pool until the window expires."""
        today = date.today().isoformat()
        docs  = await self._solved.find(
            {"student_id": student_id, "next_review_date": {"$gt": today}},
            {"question_id": 1, "_id": 0},
        ).to_list(length=None)
        return {d["question_id"] for d in docs}

    async def get_due_review_questions(self, student_id: str, limit: int = 5) -> list[dict]:
        """Correctly-solved questions whose SM-2 review date has arrived."""
        today = date.today().isoformat()
        return await self._solved.find(
            {"student_id": student_id, "next_review_date": {"$lte": today}, "last_correct": True},
            {"_id": 0},
            sort=[("next_review_date", ASCENDING)],
            limit=limit,
        ).to_list(length=limit)

    async def get_due_incorrect_questions(self, student_id: str, limit: int = 5) -> list[dict]:
        """Incorrectly-answered questions whose short retry window has arrived."""
        today = date.today().isoformat()
        return await self._solved.find(
            {"student_id": student_id, "next_review_date": {"$lte": today}, "last_correct": False},
            {"_id": 0},
            sort=[("consecutive_incorrect", DESCENDING), ("next_review_date", ASCENDING)],
            limit=limit,
        ).to_list(length=limit)

    # --- agent tool query methods ---

    async def tool_get_unlocked_topics(self, student_id: str) -> list[dict]:
        all_states = await self.get_topic_states_dict(student_id)
        graph      = get_prereq_graph()
        trend_map  = await self.get_trend_scores_dict()
        result = []
        for tid, state in all_states.items():
            if not PrerequisiteChecker.is_unlocked(tid, all_states, graph):
                continue
            a, b = state["alpha"], state["beta"]
            mean = a / (a + b)
            var  = (a * b) / ((a + b) ** 2 * (a + b + 1))
            result.append({
                "topic_id": tid, "chapter": state["chapter"],
                "mastery_mean": round(mean, 3), "mastery_uncertainty": round(var, 4),
                "p_appears_this_year": trend_map.get(tid, 0.5),
            })
        result.sort(key=lambda x: x["mastery_mean"])
        return result

    async def tool_get_due_reviews(self, student_id: str, limit: int = 5) -> list[dict]:
        today      = date.today().isoformat()
        due_topics = await self._states.find(
            {"student_id": student_id, "next_review_date": {"$lte": today}, "total_attempts": {"$gt": 0}},
            {"topic_id": 1, "chapter": 1, "next_review_date": 1, "_id": 0},
            limit=limit,
        ).to_list(length=limit)

        result = []
        for t in due_topics:
            today_date = date.today()
            try:
                overdue_days = max(0, (today_date - date.fromisoformat(t["next_review_date"])).days)
            except ValueError:
                overdue_days = 0
            seen = await self._history.find_one(
                {"student_id": student_id, "topic_id": t["topic_id"]},
                {"question_id": 1, "_id": 0}, sort=[("timestamp", DESCENDING)],
            )
            if seen:
                result.append({"question_id": seen["question_id"], "topic_id": t["topic_id"],
                                "chapter": t.get("chapter", ""), "overdue_days": overdue_days})
        return result

    async def tool_get_weakest_unlocked(self, student_id: str, limit: int = MAX_FOCUS_TOPICS) -> list[str]:
        unlocked = await self.tool_get_unlocked_topics(student_id)
        return [t["topic_id"] for t in unlocked[:limit]]

    async def tool_get_trend_top_topics(self, limit: int = 10) -> list[dict]:
        return await self._trends.find(
            {}, {"topic_id": 1, "p_appears": 1, "chapter": 1, "_id": 0},
            sort=[("p_appears", DESCENDING)], limit=limit,
        ).to_list(length=limit)

    async def tool_get_candidate_questions(
        self, topic_id: str, difficulty_min: float, difficulty_max: float,
        exclude_ids: list[str], limit: int = MAX_CANDIDATE_QUESTIONS,
        student_id: str = "",
    ) -> list[dict]:
        chapter, topic = topic_id.split("::", 1) if "::" in topic_id else ("", topic_id)
        diff_filter = self._difficulty_band_filter(difficulty_min, difficulty_max)
        # also exclude questions the student solved that aren't due for review yet
        solved_not_due: set[str] = set()
        if student_id:
            solved_not_due = await self.get_solved_not_due_ids(student_id)
        all_excluded = list(set(exclude_ids) | solved_not_due)
        query: dict = {"chapter": chapter, "topic": topic, **diff_filter}
        if all_excluded:
            query["question_id"] = {"$nin": all_excluded}

        docs = await self._questions.find(
            query, {"_id": 0, "question_id": 1, "difficulty": 1, "year": 1, "type": 1}, limit=limit,
        ).to_list(length=limit)

        session_seen = set(exclude_ids)
        result = []
        for d in docs:
            qid = str(d.get("question_id", ""))
            if not qid: continue
            diff_str = d.get("difficulty", "medium")
            result.append({
                "question_id": qid, "difficulty": diff_str,
                "difficulty_float": self._difficulty_to_float(diff_str),
                "year": d.get("year", 0), "type": d.get("type", "single_correct"),
                "is_novel": qid not in session_seen and qid not in solved_not_due,
            })
        return result

    async def tool_get_question_type_weights(self, student_id: str) -> dict[str, float]:
        pipeline = [
            {"$match": {"student_id": student_id}},
            {"$group": {"_id": "$question_type", "total": {"$sum": 1}, "correct": {"$sum": {"$cond": ["$correct", 1, 0]}}}},
        ]
        docs = await self._history.aggregate(pipeline).to_list(length=None)
        type_acc: dict[str, float] = {}
        for d in docs:
            qtype = d["_id"] or "single_correct"
            type_acc[qtype] = d["correct"] / d["total"] if d["total"] > 0 else 0.5

        all_types = ["single_correct", "multi_correct", "integer", "matching"]
        for t in all_types:
            type_acc.setdefault(t, 0.5)
        raw   = {t: 1.0 - type_acc[t] for t in all_types}
        total = sum(raw.values()) or 1.0
        return {t: round(w / total, 3) for t, w in raw.items()}

    async def tool_get_topic_attempt_stats(self, student_id: str, topic_ids: list[str]) -> dict[str, dict]:
        pipeline = [
            {"$match": {"student_id": student_id, "topic_id": {"$in": topic_ids}}},
            {"$group": {
                "_id": "$topic_id", "total": {"$sum": 1},
                "correct": {"$sum": {"$cond": ["$correct", 1, 0]}},
                "avg_time_ms": {"$avg": "$time_ms"},
                "outcomes": {"$push": "$correct"},
                "difficulties": {"$push": "$difficulty"},
            }},
        ]
        docs     = await self._history.aggregate(pipeline).to_list(length=None)
        pop_stats = await self._get_population_time_stats()
        result: dict[str, dict] = {}
        for d in docs:
            tid         = d["_id"]
            outcomes    = d["outcomes"]
            difficulties = [self._difficulty_to_float(x) if isinstance(x, str) else x for x in d["difficulties"]]
            avg_ms      = d["avg_time_ms"] or 0.0
            inconsistency = ErrorTaxonomyComputer.compute_inconsistency_rate(outcomes)
            ceiling     = ErrorTaxonomyComputer.compute_difficulty_ceiling(difficulties, outcomes)
            time_z      = ErrorTaxonomyComputer.compute_time_z_score(avg_ms, pop_stats.get("mean_ms", avg_ms), pop_stats.get("std_ms", 1.0))
            result[tid] = {
                "total_attempts": d["total"], "correct": d["correct"],
                "avg_time_seconds": round(avg_ms / 1000, 1),
                "inconsistency_rate": round(inconsistency, 3),
                "difficulty_ceiling": round(ceiling, 2),
                "time_z_score": round(time_z, 2),
            }
        return result

    async def tool_get_error_clusters(self, student_id: str, n_recent: int = ERROR_CLUSTER_WINDOW) -> dict[str, dict]:
        history   = await self.get_recent_history(student_id, limit=n_recent)
        by_topic: dict[str, list] = {}
        for event in history:
            by_topic.setdefault(event.get("topic_id", ""), []).append(event)

        pop_stats = await self._get_population_time_stats()
        result: dict[str, dict] = {}
        for tid, events in by_topic.items():
            if len(events) < 3: continue
            outcomes     = [e["correct"] for e in events]
            difficulties = [self._difficulty_to_float(e.get("difficulty", 0.0)) if isinstance(e.get("difficulty"), str) else float(e.get("difficulty", 0.0)) for e in events]
            avg_ms       = sum(e.get("time_ms", 0) for e in events) / len(events)
            inconsistency = ErrorTaxonomyComputer.compute_inconsistency_rate(outcomes)
            ceiling      = ErrorTaxonomyComputer.compute_difficulty_ceiling(difficulties, outcomes)
            time_z       = ErrorTaxonomyComputer.compute_time_z_score(avg_ms, pop_stats.get("mean_ms", avg_ms), pop_stats.get("std_ms", 1.0))
            error_type   = ErrorTaxonomyComputer.classify_error_type(inconsistency, ceiling, time_z)
            result[tid]  = {"dominant_error_type": error_type, "confidence": round(min(len(events) / 10.0, 1.0), 2)}
        return result

    # --- catalog: subjects / chapters (for Physics & Chemistry support) --------

    async def get_catalog_subjects(self) -> list[dict]:
        """Distinct subjects in the questions catalog with chapter breakdown."""
        pipeline = [
            {"$group": {"_id": {"subject": "$subject", "chapter": "$chapter"}, "count": {"$sum": 1}}},
            {"$sort": {"_id.subject": 1, "_id.chapter": 1}},
        ]
        docs = await self._questions.aggregate(pipeline).to_list(length=None)
        # Build {subject: {chapter: count}} dict
        by_subject: dict[str, dict[str, int]] = {}
        for d in docs:
            sub = (d["_id"].get("subject") or "").lower().strip()
            ch  = d["_id"].get("chapter") or ""
            if not sub or not ch:
                continue
            by_subject.setdefault(sub, {})[ch] = d["count"]
        result = []
        for sub, chapters in sorted(by_subject.items()):
            result.append({
                "subject": sub,
                "chapters": [{"chapter": ch, "topic_count": cnt} for ch, cnt in chapters.items()],
                "topic_count": sum(chapters.values()),
            })
        return result

    async def get_catalog_topics_for_subject(self, subject: str) -> list[dict]:
        """Return distinct (chapter, topic) pairs for a given subject."""
        pipeline = [
            {"$match": {"subject": {"$regex": f"^{subject}$", "$options": "i"}}},
            {"$group": {"_id": {"chapter": "$chapter", "topic": "$topic"}}},
            {"$sort": {"_id.chapter": 1, "_id.topic": 1}},
        ]
        docs = await self._questions.aggregate(pipeline).to_list(length=None)
        return [
            {"chapter": d["_id"]["chapter"], "topic": d["_id"]["topic"]}
            for d in docs if d["_id"].get("chapter") and d["_id"].get("topic")
        ]

    async def initialize_student_for_subject(self, student_id: str, subject: str) -> int:
        """Create topic states for all catalog topics belonging to *subject*.
        Skips topics that already have a state doc (upsert-safe via unique index)."""
        topics = await self.get_catalog_topics_for_subject(subject)
        if not topics:
            return 0
        docs = [
            new_student_topic_state_doc(
                student_id,
                topic_id=f"{t['chapter']}::{t['topic']}",
                chapter=t["chapter"],
                subject=subject,
            )
            for t in topics
        ]
        try:
            result = await self._states.insert_many(docs, ordered=False)
            return len(result.inserted_ids)
        except Exception as exc:
            inserted = getattr(exc, "details", {}).get("nInserted", 0)
            logger.warning("Partial %s init for %s: %d new, err: %s", subject, student_id, inserted, exc)
            return inserted

    # --- attempted questions with question text --------------------------------

    async def get_attempted_questions_with_content(
        self, student_id: str, correct: bool, limit: int = 20,
    ) -> list[dict]:
        """Return the last *limit* history events (filtered by correctness) joined with
        question text from the catalog."""
        history = await self._history.find(
            {"student_id": student_id, "correct": correct},
            {"_id": 0},
            sort=[("timestamp", DESCENDING)],
            limit=limit,
        ).to_list(length=limit)

        if not history:
            return []

        # Batch-fetch question details from the catalog
        q_ids = list({e["question_id"] for e in history})
        q_docs = await self._questions.find(
            {"question_id": {"$in": q_ids}},
            {"_id": 0, "question_id": 1, "question": 1, "options": 1,
             "correct_options": 1, "correct_answer": 1, "year": 1,
             "isImgQuestion": 1, "subject": 1},
        ).to_list(length=None)
        q_map = {str(d.get("question_id", "")): d for d in q_docs}

        result = []
        for event in history:
            qid  = event["question_id"]
            qcat = q_map.get(qid, {})
            opts = [
                {"identifier": o.get("identifier", ""), "content": o.get("content", "")}
                for o in (qcat.get("options") or [])
            ]
            result.append({
                "question_id":     qid,
                "topic_id":        event.get("topic_id", ""),
                "chapter":         event.get("chapter", ""),
                "subject":         qcat.get("subject", event.get("subject", SUBJECT_MATHEMATICS)),
                "correct":         correct,
                "difficulty":      event.get("difficulty"),
                "question_type":   event.get("question_type", "single_correct"),
                "timestamp":       event.get("timestamp"),
                "question_text":   qcat.get("question", ""),
                "options":         opts,
                "correct_options": [str(x) for x in (qcat.get("correct_options") or [])],
                "correct_answer":  str(qcat["correct_answer"]) if qcat.get("correct_answer") is not None else None,
                "year":            qcat.get("year"),
                "is_image_question": bool(qcat.get("isImgQuestion", False)),
            })
        return result

    async def get_question_by_pyq_id(self, question_id: str) -> Optional[dict]:
        return await self._questions.find_one({"question_id": question_id})

    async def get_student_stats(self, student_id: str) -> dict:
        pipeline = [
            {"$match": {"student_id": student_id}},
            {"$group": {
                "_id": None,
                "total_attempts":  {"$sum": "$total_attempts"},
                "total_correct":   {"$sum": "$total_correct"},
                "topics_attempted": {"$sum": {"$cond": [{"$gt": ["$total_attempts", 0]}, 1, 0]}},
                "topics_mastered": {"$sum": {"$cond": [{"$gte": ["$mastery_mean", 0.8]}, 1, 0]}},
                "unlocked_count":  {"$sum": {"$cond": ["$is_unlocked", 1, 0]}},
            }},
        ]
        docs = await self._states.aggregate(pipeline).to_list(length=1)
        if not docs:
            return {"total_attempts": 0, "total_correct": 0, "topics_attempted": 0, "topics_mastered": 0, "unlocked_count": 0}
        return docs[0]

    async def tool_get_topic_year_matrix(self) -> dict[str, dict[int, int]]:
        pipeline = [{"$group": {"_id": {"chapter": "$chapter", "topic": "$topic", "year": "$year"}, "count": {"$sum": 1}}}]
        docs   = await self._questions.aggregate(pipeline).to_list(length=None)
        matrix: dict[str, dict[int, int]] = {}
        for d in docs:
            chapter = d["_id"].get("chapter", "")
            topic   = d["_id"].get("topic", "")
            year    = d["_id"].get("year")
            if not chapter or not topic or not year: continue
            matrix.setdefault(f"{chapter}::{topic}", {})[int(year)] = d["count"]
        return matrix

    async def tool_flag_prerequisite_gap(self, student_id: str, topic_id: str, gap_type: str) -> None:
        note = f"[{gap_type.upper()}] {topic_id}"
        await self._personality.update_one(
            {"student_id": student_id},
            {
                "$addToSet": {"avoidance_topics" if "avoidance" in gap_type else "persistent_weak_chapters": topic_id},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
            upsert=True,
        )
        logger.info("Flagged %s for student %s: %s", gap_type, student_id, note)

    # --- internal helpers ---

    async def _get_population_time_stats(self) -> dict[str, float]:
        pipeline = [{"$group": {"_id": None, "mean": {"$avg": "$time_ms"}, "count": {"$sum": 1}}}]
        docs = await self._history.aggregate(pipeline).to_list(length=1)
        if not docs: return {"mean_ms": 60000.0, "std_ms": 30000.0}
        return {"mean_ms": docs[0].get("mean", 60000.0), "std_ms": 30000.0}

    @staticmethod
    def _difficulty_to_float(difficulty: str | float) -> float:
        if isinstance(difficulty, (int, float)): return float(difficulty)
        return {"easy": -1.0, "medium": 0.0, "hard": 1.0}.get(str(difficulty).lower(), 0.0)

    @staticmethod
    def _difficulty_band_filter(diff_min: float, diff_max: float) -> dict:
        mapping = {"easy": -1.0, "medium": 0.0, "hard": 1.0}
        candidates = [label for label, val in mapping.items() if diff_min - 0.7 <= val <= diff_max + 0.7]
        return {"difficulty": {"$in": candidates or ["medium"]}}
