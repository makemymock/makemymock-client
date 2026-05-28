"""
Groq-powered agent classes for the JEE Recommender agentic layer.

Four agents, each with a distinct role and runtime profile:

  SessionPlannerAgent     — runs at session start (~3 s), uses HEAVY model
  QuestionSelectorAgent   — runs per-question (~1 s), uses FAST model
  DiagnosisAgent          — runs after session end / frustration, uses HEAVY model
  TrendIntelligenceAgent  — runs weekly, uses HEAVY model + TrendScoreComputer

All agents are async. They receive minimal context (< 1500 tokens total) and
call tools to fetch the data they need (§5.2: agents get tools, not raw data).
None are called in the per-question hot path directly — only QuestionSelectorAgent
is close to hot, but even it runs asynchronously and the result is awaited.

The Diagnosis Agent and Trend Agent are fire-and-forget via asyncio.create_task
in the service layer — they never block the HTTP response.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from config.settings import settings
from modules.recommender.repository import RecommenderRepository
from modules.recommender.tools import (
    DIAGNOSIS_TOOLS,
    QUESTION_SELECTOR_TOOLS,
    SESSION_PLANNER_TOOLS,
    make_tool_executor,
)
from modules.recommender.trend_engine import TrendScoreComputer
from modules.recommender.models import new_topic_trend_doc
from services.groq_client import GroqClientError, chat_with_tools, chat_json

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared prompt utilities
# ---------------------------------------------------------------------------

def _personality_to_context(personality: dict[str, Any]) -> str:
    """Serialize the student personality doc to a compact JSON block (≤400 tokens)."""
    compact = {
        "learning_style": personality.get("learning_style", "balanced"),
        "fatigue_threshold_questions": personality.get("fatigue_threshold_questions", 20),
        "confidence_profile": personality.get("confidence_profile", "resilient"),
        "improvement_rate": personality.get("improvement_rate", "medium"),
        "strong_chapters": personality.get("strong_chapters", [])[:5],
        "persistent_weak_chapters": personality.get("persistent_weak_chapters", [])[:5],
        "avoidance_topics": personality.get("avoidance_topics", [])[:5],
        "question_type_strengths": personality.get("question_type_strengths", {}),
        "error_profile": personality.get("error_profile", {}),
        "notes": (personality.get("notes", "") or "")[:300],
    }
    return json.dumps(compact, indent=None, separators=(",", ":"))


def _summaries_to_context(summaries: list[dict[str, Any]]) -> str:
    """Serialize last-N session summaries to a compact string (≤450 tokens)."""
    compact = []
    for s in summaries[:3]:
        compact.append({
            "date": str(s.get("created_at", ""))[:10],
            "questions": s.get("questions_attempted", 0),
            "accuracy_by_chapter": s.get("accuracy_by_chapter", {}),
            "frustration_events": s.get("frustration_events_count", 0),
            "topics_unlocked": s.get("topics_unlocked", []),
            "first_half_acc": s.get("first_half_accuracy", 0.0),
            "second_half_acc": s.get("second_half_accuracy", 0.0),
        })
    return json.dumps(compact, separators=(",", ":"))


# ---------------------------------------------------------------------------
# SessionPlannerAgent — §4.2
# ---------------------------------------------------------------------------

class SessionPlannerAgent:
    """
    Plans the study session at startup using student personality, recent history,
    and trend/mastery data fetched via tools.

    Runs once per session (~3 s). Uses the HEAVY model for deeper reasoning.
    Output is a session plan that pre-filters the Thompson Sampling topic pool.
    """

    SYSTEM_PROMPT = """You are a JEE expert tutor and session planner. You receive a student's personality profile and recent session history. Your job is to create an optimal study session plan.

Use the available tools to gather data, then output a JSON session plan with exactly these fields:
{
  "focus_topics": ["chapter::topic", ...],  // 3-5 topic IDs to prioritize this session
  "session_mode": "drilling" | "review" | "mixed" | "recovery",
  "start_difficulty_offset": -0.5 to 0.5,  // negative = start easier, positive = start harder
  "review_injection_rate": 0.1 to 0.4,     // fraction of slots to use for spaced repetition
  "confidence_note": "..."                  // 1-2 sentence note on the student's current state
}

Rules:
- If confidence_profile is "brittle" and recent frustration_events > 0, use session_mode "recovery" and start_difficulty_offset <= -0.3
- Include high p_appears topics (exam trend) AND weak topics in focus_topics
- Always include at least one topic with p_appears > 0.6 if available
- Output ONLY the JSON object, no extra text"""

    # Student-friendly labels for each tool the agent can call
    _TOOL_LABELS: dict[str, str] = {
        "get_unlocked_topics":    "Checked which topics you've unlocked so far",
        "get_due_reviews":        "Checked which topics are due for spaced repetition",
        "get_weakest_unlocked":   "Identified your weakest unlocked topics",
        "get_trend_top_topics":   "Looked at which topics appear most in JEE exams",
        "get_candidate_questions":"Scanned available questions for your level",
        "get_question_type_weights": "Checked your performance across question types",
        "get_topic_attempt_stats":"Reviewed your attempt history per topic",
        "get_error_clusters":     "Analyzed your error patterns",
        "get_session_summary":    "Reviewed your recent session data",
    }

    async def run(
        self,
        student_id: str,
        db: AsyncIOMotorDatabase,
    ) -> dict[str, Any]:
        """
        Execute the session planning agentic loop.

        Returns a dict with focus_topics, session_mode, start_difficulty_offset,
        review_injection_rate, confidence_note. Falls back to safe defaults on error.
        """
        repo = RecommenderRepository(db)
        personality = await repo.get_personality(student_id) or {}
        summaries = await repo.get_last_n_session_summaries(student_id, n=3)

        personality_ctx = _personality_to_context(personality)
        summaries_ctx = _summaries_to_context(summaries)

        user_message = (
            f"Student personality:\n{personality_ctx}\n\n"
            f"Last 3 sessions:\n{summaries_ctx}\n\n"
            "Call the tools to get topic data, then output the session plan JSON."
        )

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        executor = make_tool_executor(db, student_id)

        try:
            final_text, tool_calls = await chat_with_tools(
                messages=messages,
                tools=SESSION_PLANNER_TOOLS,
                tool_executor=executor,
                model=settings.GROQ_MODEL_HEAVY,
                temperature=0.15,
                max_tokens=2048,
                max_tool_rounds=5,
            )
            logger.info(
                "SessionPlannerAgent completed for %s. Tools called: %d",
                student_id,
                len(tool_calls),
            )
            plan = self._parse_plan(final_text)
            plan["reasoning_steps"] = [
                self._TOOL_LABELS[tc["name"]]
                for tc in tool_calls
                if tc["name"] in self._TOOL_LABELS
            ]
        except GroqClientError as exc:
            logger.warning("SessionPlannerAgent failed for %s: %s. Using fallback.", student_id, exc)
            plan = self._fallback_plan(personality)

        return plan

    @staticmethod
    def _parse_plan(text: str) -> dict[str, Any]:
        """Extract and validate the JSON session plan from the model's response."""
        try:
            # Find the JSON object in the response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start == -1 or end == 0:
                raise ValueError("No JSON found")
            plan = json.loads(text[start:end])
            # Validate required fields
            plan.setdefault("focus_topics", [])
            plan.setdefault("session_mode", "mixed")
            plan.setdefault("start_difficulty_offset", 0.0)
            plan.setdefault("review_injection_rate", 0.25)
            plan.setdefault("confidence_note", "")
            # Clamp numeric fields
            plan["start_difficulty_offset"] = max(-1.0, min(1.0, float(plan["start_difficulty_offset"])))
            plan["review_injection_rate"] = max(0.0, min(0.5, float(plan["review_injection_rate"])))
            return plan
        except Exception as exc:
            logger.warning("Failed to parse SessionPlannerAgent response: %s | text: %.200s", exc, text)
            return SessionPlannerAgent._fallback_plan({})

    @staticmethod
    def _fallback_plan(personality: dict[str, Any]) -> dict[str, Any]:
        """Safe default plan when the agent fails."""
        return {
            "focus_topics": [],
            "session_mode": "mixed",
            "start_difficulty_offset": 0.0,
            "review_injection_rate": 0.25,
            "confidence_note": "Starting with a balanced session.",
        }


# ---------------------------------------------------------------------------
# QuestionSelectorAgent — §4.3
# ---------------------------------------------------------------------------

class QuestionSelectorAgent:
    """
    Selects the single best question from 10 candidates for the current slot.

    Runs per-question (~1 s) using the FAST model. Context is minimal:
    student error profile + candidate list. No personality doc needed.
    """

    SYSTEM_PROMPT = """You are a JEE question selector. You receive:
- The student's error profile and question-type weaknesses
- A list of candidate questions with metadata

Your job is to select the single best question_id from the candidates.

Selection criteria (in priority order):
1. Match the student's weak question_type (higher weight = needs more practice)
2. Prefer novel questions (is_novel: true) over repeated ones
3. Prefer more recent years (higher year = more exam-relevant)
4. Match the requested difficulty as closely as possible

Output ONLY a JSON object: {"selected_question_id": "..."} — no other text."""

    async def run(
        self,
        student_id: str,
        topic_id: str,
        difficulty_min: float,
        difficulty_max: float,
        seen_correct_ids: list[str],
        error_profile: dict[str, str],
        db: AsyncIOMotorDatabase,
    ) -> str | None:
        """
        Select the best question for the given topic and difficulty band.

        Returns the selected question_id string, or None if no candidates exist.
        Falls back to the first candidate if the agent fails.
        """
        executor = make_tool_executor(db, student_id)

        # First fetch candidates so we can bail early if empty
        repo = RecommenderRepository(db)
        candidates = await repo.tool_get_candidate_questions(
            topic_id=topic_id,
            difficulty_min=difficulty_min,
            difficulty_max=difficulty_max,
            exclude_ids=seen_correct_ids,
            limit=10,
        )

        if not candidates:
            logger.info("No candidates for topic=%s in difficulty [%.1f, %.1f]", topic_id, difficulty_min, difficulty_max)
            return None

        type_weights = await repo.tool_get_question_type_weights(student_id)

        user_message = (
            f"Error profile: {json.dumps(error_profile)}\n"
            f"Type improvement weights: {json.dumps(type_weights)}\n"
            f"Candidates: {json.dumps(candidates)}\n\n"
            "Select the best question_id."
        )

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        try:
            # QuestionSelector doesn't need tool calls — data is already in the prompt
            response_text = await chat_json(
                user_message,
                model=settings.GROQ_MODEL_FAST,
                system=self.SYSTEM_PROMPT,
                temperature=0.05,
                max_tokens=64,
            )
            start = response_text.find("{")
            end = response_text.rfind("}") + 1
            if start != -1 and end > 0:
                result = json.loads(response_text[start:end])
                selected = result.get("selected_question_id")
                # Validate the returned ID is actually in our candidates
                valid_ids = {c["question_id"] for c in candidates}
                if selected in valid_ids:
                    return selected
        except Exception as exc:
            logger.warning("QuestionSelectorAgent failed: %s. Falling back to first candidate.", exc)

        # Fallback: score candidates ourselves without LLM
        return self._score_and_pick(candidates, type_weights, error_profile)

    @staticmethod
    def _score_and_pick(
        candidates: list[dict[str, Any]],
        type_weights: dict[str, float],
        error_profile: dict[str, str],
    ) -> str | None:
        """Deterministic fallback when the LLM is unavailable."""
        if not candidates:
            return None
        best = max(
            candidates,
            key=lambda c: (
                type_weights.get(c.get("type", "single_correct"), 0.25)
                + (0.2 if c.get("is_novel") else 0.0)
                + (c.get("year", 2019) - 2019) * 0.02
            ),
        )
        return best["question_id"]


# ---------------------------------------------------------------------------
# DiagnosisAgent — §4.4
# ---------------------------------------------------------------------------

class DiagnosisAgent:
    """
    Analyzes session performance after session end or frustration events.

    Runs asynchronously via asyncio.create_task — never blocks a response.
    Uses the HEAVY model for nuanced error diagnosis. Updates the personality
    document and flags prerequisite gaps.
    """

    SYSTEM_PROMPT = """You are an expert JEE learning diagnostician. You receive a student's personality document. Use the tools to analyze their recent performance and update their profile.

Your tasks:
1. Call get_error_clusters to understand error patterns
2. Call get_topic_attempt_stats for topics with low mastery
3. Based on the data, call update_student_personality with targeted updates
4. If a topic shows avoidance (fast answers + low accuracy), call flag_prerequisite_gap
5. Call update_student_personality one final time with a notes update summarizing your findings

When updating personality, update only the fields you have evidence for. Do not guess.
After all tool calls, output a brief JSON summary: {"diagnosis_complete": true, "main_finding": "..."}"""

    async def run(
        self,
        student_id: str,
        session_id: str,
        trigger: str,  # "session_end" | "frustration"
        db: AsyncIOMotorDatabase,
    ) -> None:
        """
        Run the diagnosis pipeline for a student after a session or frustration event.

        This method is fire-and-forget (called via asyncio.create_task). It logs
        results but does not return meaningful data to the caller.
        """
        repo = RecommenderRepository(db)
        personality = await repo.get_personality(student_id) or {}
        personality_ctx = _personality_to_context(personality)

        user_message = (
            f"Trigger: {trigger}\n"
            f"Session: {session_id}\n"
            f"Student personality:\n{personality_ctx}\n\n"
            "Diagnose and update the student profile. Use the tools."
        )

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        executor = make_tool_executor(db, student_id)

        try:
            final_text, tool_calls = await chat_with_tools(
                messages=messages,
                tools=DIAGNOSIS_TOOLS,
                tool_executor=executor,
                model=settings.GROQ_MODEL_HEAVY,
                temperature=0.1,
                max_tokens=2048,
                max_tool_rounds=8,
            )
            logger.info(
                "DiagnosisAgent completed for %s (trigger=%s). Tools: %d, response: %.100s",
                student_id,
                trigger,
                len(tool_calls),
                final_text,
            )
        except GroqClientError as exc:
            logger.warning("DiagnosisAgent failed for %s: %s", student_id, exc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("DiagnosisAgent unexpected error for %s: %s", student_id, exc)


# ---------------------------------------------------------------------------
# TrendIntelligenceAgent — §4.5
# ---------------------------------------------------------------------------

class TrendIntelligenceAgent:
    """
    Computes and stores JEE topic appearance probabilities weekly.

    The heavy lifting is done by TrendScoreComputer (pure math). This agent
    orchestrates: fetch year matrix → compute all scores → persist → optionally
    ask the LLM to flag anomalies (topics whose trend changed sharply this week).
    """

    async def run(self, db: AsyncIOMotorDatabase) -> int:
        """
        Run the weekly trend intelligence pipeline.

        Returns the number of topics updated in topic_trend_scores.
        """
        repo = RecommenderRepository(db)

        # Step 1: fetch topic × year matrix from the questions catalog
        logger.info("TrendIntelligenceAgent: fetching year matrix...")
        year_matrix = await repo.tool_get_topic_year_matrix()
        if not year_matrix:
            logger.warning("TrendIntelligenceAgent: year matrix is empty. No questions catalog?")
            return 0

        # Build topic → chapter mapping from the matrix keys
        topic_chapters = {
            topic_id: topic_id.split("::")[0]
            for topic_id in year_matrix
        }

        # Step 2: run the trend score computation pipeline
        current_year = datetime.now(timezone.utc).year
        scorer = TrendScoreComputer(current_year=current_year)
        logger.info("TrendIntelligenceAgent: computing scores for %d topics...", len(year_matrix))
        results = scorer.compute_all(year_matrix, topic_chapters)

        # Step 3: persist all scores to MongoDB
        updated = 0
        for topic_id, data in results.items():
            doc = new_topic_trend_doc(
                topic_id=topic_id,
                chapter=data.chapter,
                p_appears=data.p_appears,
                trend_score_raw=data.trend_score_raw,
                gap_bonus=data.gap_bonus,
                streak_score=data.streak_score,
                direction_multiplier=data.direction_multiplier,
            )
            await repo.upsert_trend_score(doc)
            updated += 1

        # Step 4: ask the LLM to summarize anomalies — truly fire-and-forget
        high_priority = scorer.high_priority_topics(results)
        asyncio.create_task(self._log_anomalies(results, high_priority))

        logger.info("TrendIntelligenceAgent: updated %d topic trend scores.", updated)
        return updated

    async def _log_anomalies(
        self,
        results: dict,
        high_priority: list[str],
    ) -> None:
        """Ask the LLM to flag trend anomalies and log them. Non-critical."""
        try:
            top_5 = sorted(results.values(), key=lambda x: x.p_appears, reverse=True)[:5]
            summary = [
                {"topic_id": d.topic_id, "p_appears": d.p_appears, "gap_bonus": d.gap_bonus}
                for d in top_5
            ]
            prompt = (
                f"Top 5 JEE topics by exam appearance probability this year:\n"
                f"{json.dumps(summary, indent=2)}\n\n"
                f"Total high-priority topics (p > 0.7): {len(high_priority)}\n\n"
                "In 1-2 sentences, flag any surprising trends worth noting for exam preparation."
            )
            note = await chat_json(
                prompt,
                model=settings.GROQ_MODEL_HEAVY,
                system="You are a JEE exam trend analyst. Be concise.",
                temperature=0.3,
                max_tokens=128,
            )
            logger.info("TrendIntelligenceAgent anomaly note: %s", note.strip())
        except Exception as exc:  # noqa: BLE001
            logger.debug("TrendIntelligenceAgent anomaly logging skipped: %s", exc)
