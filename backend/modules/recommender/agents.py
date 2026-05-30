from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

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
from services.gemini_client import GeminiClientError, chat_with_tools, chat_json

logger = logging.getLogger(__name__)


def _personality_to_context(p: dict) -> str:
    return json.dumps({
        "learning_style": p.get("learning_style", "balanced"),
        "fatigue_threshold_questions": p.get("fatigue_threshold_questions", 20),
        "confidence_profile": p.get("confidence_profile", "resilient"),
        "improvement_rate": p.get("improvement_rate", "medium"),
        "strong_chapters": p.get("strong_chapters", [])[:5],
        "persistent_weak_chapters": p.get("persistent_weak_chapters", [])[:5],
        "avoidance_topics": p.get("avoidance_topics", [])[:5],
        "question_type_strengths": p.get("question_type_strengths", {}),
        "error_profile": p.get("error_profile", {}),
        "notes": (p.get("notes") or "")[:300],
    }, separators=(",", ":"))


def _summaries_to_context(summaries: list[dict]) -> str:
    return json.dumps([{
        "date": str(s.get("created_at", ""))[:10],
        "questions": s.get("questions_attempted", 0),
        "accuracy_by_chapter": s.get("accuracy_by_chapter", {}),
        "frustration_events": s.get("frustration_events_count", 0),
        "topics_unlocked": s.get("topics_unlocked", []),
        "first_half_acc": s.get("first_half_accuracy", 0.0),
        "second_half_acc": s.get("second_half_accuracy", 0.0),
    } for s in summaries[:3]], separators=(",", ":"))


class SessionPlannerAgent:
    SYSTEM_PROMPT = """You are a JEE expert tutor and personalised session planner.

You will receive a student's personality profile and recent session history.
Call the provided tools to gather live data (weak topics, due reviews, exam trends),
then produce a session plan.

After all tool calls are complete, output a single JSON object — nothing else, no markdown fences:
{
  "focus_topics": ["chapter::topic", ...],
  "session_mode": "drilling" | "review" | "mixed" | "recovery",
  "start_difficulty_offset": -0.3 to 0.3,
  "review_injection_rate": 0.1 to 0.4,
  "confidence_note": "1-2 sentences describing the student's current state and what today's session targets"
}

Planning rules:
- focus_topics: 3-5 topic IDs. Blend the weakest unlocked topics with at least one high-trend (p_appears > 0.6) topic.
- session_mode: use "recovery" if confidence_profile is "brittle" AND frustration_events > 0 in recent sessions; "drilling" if accuracy trend is improving; "review" if many topics are due for spaced repetition; otherwise "mixed".
- start_difficulty_offset: negative (easier) for recovery or low-confidence students; positive (harder) for students on a winning streak.
- confidence_note: speak directly to the student using "you". Name their strongest and weakest topic explicitly. Example: "You've been doing well in Complex Numbers, but Limits is where you're struggling the most right now — that's what we're targeting today."""

    _TOOL_LABELS = {
        "get_unlocked_topics":       "Looked at all the topics you've unlocked so far",
        "get_due_reviews":           "Found questions you solved before that are ready for you to review again",
        "get_weakest_unlocked":      "Found the topics where you need the most work right now",
        "get_trend_top_topics":      "Checked which topics come up most often in JEE exams",
        "get_candidate_questions":   "Browsed questions at the right difficulty level for you",
        "get_question_type_weights": "Checked which question types you struggle with the most",
        "get_topic_attempt_stats":   "Analysed your attempt history to see where you get stuck",
        "get_error_clusters":        "Looked at the kinds of mistakes you've been making",
        "get_session_summary":       "Reviewed how your last session went",
    }
    

    async def run(
        self,
        student_id: str,
        db: AsyncIOMotorDatabase,
        *,
        on_step=None,
    ) -> dict:
        repo = RecommenderRepository(db)
        personality = await repo.get_personality(student_id) or {}
        summaries = await repo.get_last_n_session_summaries(student_id, n=3)

        user_message = (
            f"Student personality:\n{_personality_to_context(personality)}\n\n"
            f"Last 3 sessions:\n{_summaries_to_context(summaries)}\n\n"
            "Call the tools to get topic data, then output the session plan JSON."
        )

        # Closure that fires the on_step callback after each tool call completes.
        _seen_count: list[int] = [0]

        async def _on_tool_result(_round_num: int, tool_name: str, _args: dict, _result: object) -> None:
            label = self._TOOL_LABELS.get(tool_name)
            if on_step and label:
                idx = _seen_count[0]
                _seen_count[0] += 1
                await on_step({"type": "step", "tool": tool_name, "label": label, "index": idx})

        try:
            final_text, tool_calls = await chat_with_tools(
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                tools=SESSION_PLANNER_TOOLS,
                tool_executor=make_tool_executor(db, student_id),
                model=settings.RECOMMENDER_MODEL_HEAVY,
                temperature=0.15,
                max_tokens=2048,
                max_tool_rounds=5,
                on_tool_result=_on_tool_result if on_step else None,
            )
            logger.info("SessionPlannerAgent done for %s, tools=%d", student_id, len(tool_calls))
            plan = self._parse_plan(final_text)
            plan["reasoning_steps"] = [
                self._TOOL_LABELS[tc["name"]]
                for tc in tool_calls if tc["name"] in self._TOOL_LABELS
            ]
            # Emit confidence note as a separate event so the frontend can
            # display it with a typewriter effect independently of the step list.
            if on_step and plan.get("confidence_note"):
                await on_step({"type": "confidence", "text": plan["confidence_note"]})
        except GeminiClientError as exc:
            logger.warning("SessionPlannerAgent failed for %s: %s", student_id, exc)
            plan = self._fallback_plan(personality)

        return plan

    @staticmethod
    def _parse_plan(text: str) -> dict:
        try:
            start, end = text.find("{"), text.rfind("}") + 1
            if start == -1 or end == 0:
                raise ValueError("no JSON found")
            plan = json.loads(text[start:end])
            plan.setdefault("focus_topics", [])
            plan.setdefault("session_mode", "mixed")
            plan.setdefault("start_difficulty_offset", 0.0)
            plan.setdefault("review_injection_rate", 0.25)
            plan.setdefault("confidence_note", "")
            plan["start_difficulty_offset"] = max(-1.0, min(1.0, float(plan["start_difficulty_offset"])))
            plan["review_injection_rate"]   = max(0.0,  min(0.5,  float(plan["review_injection_rate"])))
            return plan
        except Exception as exc:
            logger.warning("Failed to parse plan: %s | text: %.200s", exc, text)
            return SessionPlannerAgent._fallback_plan({})

    @staticmethod
    def _fallback_plan(*_) -> dict:
        return {
            "focus_topics": [],
            "session_mode": "mixed",
            "start_difficulty_offset": 0.0,
            "review_injection_rate": 0.25,
            "confidence_note": "Starting with a balanced session.",
        }


class QuestionSelectorAgent:
    SYSTEM_PROMPT = """
    You are a JEE question selector. Select the single best question for this student.

You receive the student's error profile, question-type priority weights, and a candidate list.

Selection priority (most important first):
1. Highest type_weight value → student needs the most practice in that question type
2. is_novel: true → fresh questions are more valuable than repeats
3. Most recent year → newer exam questions are more relevant
4. Closest difficulty to the requested target

Respond with exactly this JSON and nothing else:{"selected_question_id": "<id>"}
"""

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
        repo = RecommenderRepository(db)
        candidates = await repo.tool_get_candidate_questions(
            topic_id=topic_id,
            difficulty_min=difficulty_min,
            difficulty_max=difficulty_max,
            exclude_ids=seen_correct_ids,
            limit=10,
            student_id=student_id,
        )
        if not candidates:
            logger.info("No candidates for topic=%s difficulty=[%.1f,%.1f]", topic_id, difficulty_min, difficulty_max)
            return None

        type_weights = await repo.tool_get_question_type_weights(student_id)
        user_message = (
            f"Error profile: {json.dumps(error_profile)}\n"
            f"Type improvement weights: {json.dumps(type_weights)}\n"
            f"Candidates: {json.dumps(candidates)}\n\n"
            "Select the best question_id."
        )

        try:
            resp = await chat_json(
                user_message,
                model=settings.RECOMMENDER_MODEL_FAST,
                system=self.SYSTEM_PROMPT,
                temperature=0.05,
                max_tokens=64,
            )
            start, end = resp.find("{"), resp.rfind("}") + 1
            if start != -1 and end > 0:
                selected = json.loads(resp[start:end]).get("selected_question_id")
                valid_ids = {c["question_id"] for c in candidates}
                if selected in valid_ids:
                    return selected
        except Exception as exc:
            logger.warning("QuestionSelectorAgent failed: %s, falling back", exc)

        return self._score_and_pick(candidates, type_weights, error_profile)

    @staticmethod
    def _score_and_pick(candidates: list[dict], type_weights: dict, _error_profile: dict) -> str | None:
        if not candidates:
            return None
        best = max(candidates, key=lambda c: (
            type_weights.get(c.get("type", "single_correct"), 0.25)
            + (0.2 if c.get("is_novel") else 0.0)
            + (c.get("year", 2019) - 2019) * 0.02
        ))
        return best["question_id"]


class DiagnosisAgent:
    SYSTEM_PROMPT = """You are an expert JEE learning diagnostician. Your job is to analyse a student's recent performance data and update their learning profile accordingly.

Workflow — follow this order:
1. Call get_error_clusters to identify the dominant error type (computation / conceptual / application / speed) per topic.
2. Call get_topic_attempt_stats for the 3-5 topics with the lowest mastery or most errors.
3. Call get_session_summary if a specific session triggered this diagnosis.
4. Based on the data:
   - Call update_student_personality with only the fields you have clear evidence for.
     Valid fields: learning_style, fatigue_threshold_questions, confidence_profile,
     improvement_rate, strong_chapters, persistent_weak_chapters, avoidance_topics,
     question_type_strengths, error_profile, notes.
   - If a topic shows avoidance (very fast answers combined with low accuracy), call flag_prerequisite_gap.
5. Call update_student_personality a final time to write a concise notes summary of your findings.

Rules:
- Only update fields where you have data evidence. Do not guess.
- notes should be 2-3 sentences: dominant error type, worst topic, recommended focus.

After all tool calls are done, output exactly this JSON and nothing else:
{"diagnosis_complete": true, "main_finding": "<one sentence summary>"}"""

    async def run(self, student_id: str, session_id: str, trigger: str, db: AsyncIOMotorDatabase) -> None:
        repo = RecommenderRepository(db)
        personality = await repo.get_personality(student_id) or {}

        user_message = (
            f"Trigger: {trigger}\n"
            f"Session: {session_id}\n"
            f"Student personality:\n{_personality_to_context(personality)}\n\n"
            "Diagnose and update the student profile. Use the tools."
        )

        try:
            final_text, tool_calls = await chat_with_tools(
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                tools=DIAGNOSIS_TOOLS,
                tool_executor=make_tool_executor(db, student_id),
                model=settings.RECOMMENDER_MODEL_HEAVY,
                temperature=0.1,
                max_tokens=2048,
                max_tool_rounds=8,
            )
            logger.info("DiagnosisAgent done for %s (trigger=%s) tools=%d response=%.100s",
                        student_id, trigger, len(tool_calls), final_text)
        except GeminiClientError as exc:
            logger.warning("DiagnosisAgent failed for %s: %s", student_id, exc)
        except Exception as exc:
            logger.exception("DiagnosisAgent unexpected error for %s: %s", student_id, exc)


class LatexConverterAgent:
    """Converts raw question text and options to KaTeX-compatible LaTeX.

    Uses gemini-3.5-flash (GEMINI_MODEL_FLASH) — cheap, fast, no tool use needed.
    Called from RecommenderService.get_question_detail() before returning to the client.
    """

    SYSTEM_PROMPT = (
        "You are a LaTeX formatter specialising in JEE (Indian engineering entrance) exam questions.\n"
        "Your job is to rewrite the question text and each option so that every mathematical expression\n"
        "is wrapped in proper KaTeX delimiters, while keeping all plain English text unchanged.\n\n"
        "Rules:\n"
        "1. Inline math  → $...$  (single dollar signs)\n"
        "2. Display math (standalone equation on its own visual line) → $$...$$\n"
        "3. Use \\frac{numerator}{denominator} for fractions, never a/b inside math.\n"
        "4. Use \\sqrt{} for square roots.\n"
        "5. Use \\vec{} for vectors, \\hat{} for unit vectors.\n"
        "6. Chemical formulas like H2O → $\\text{H}_2\\text{O}$.\n"
        "7. Greek letters: write \\alpha, \\beta, \\theta, \\omega, etc. inside $ $.\n"
        "8. Superscripts: x^2 → $x^2$, subscripts: x_0 → $x_0$.\n"
        "9. DO NOT alter any English words, units, or punctuation that are not math.\n"
        "10. DO NOT add or remove answer choices.\n"
        "11. If the text is already well-formatted LaTeX, return it unchanged.\n\n"
        "Return ONLY a JSON object with this exact shape and nothing else:\n"
        "{\"question\": \"<converted question text>\", "
        "\"options\": [{\"identifier\": \"A\", \"content\": \"<converted>\"}, ...]}\n"
        "If there are no options (integer-type question), return an empty options array."
    )

    async def convert(self, question: str, options: list[dict]) -> dict:
        """Return converted question + options dict; falls back to originals on error."""
        opts_json = json.dumps(
            [{"identifier": o.get("identifier", ""), "content": o.get("content", "")} for o in options],
            ensure_ascii=False,
        )
        prompt = f"Question:\n{question}\n\nOptions:\n{opts_json}"
        try:
            raw = await chat_json(
                prompt,
                model=settings.GEMINI_MODEL_FLASH,
                system=self.SYSTEM_PROMPT,
                temperature=0.05,
                max_tokens=2048,
            )
            start, end = raw.find("{"), raw.rfind("}") + 1
            if start == -1 or end == 0:
                raise ValueError("no JSON found")
            result = json.loads(raw[start:end])
            converted_question = result.get("question") or question
            converted_options   = result.get("options") or options
            # Safety: preserve original identifiers if model changed them
            if converted_options and len(converted_options) == len(options):
                for orig, conv in zip(options, converted_options):
                    conv["identifier"] = orig.get("identifier", conv.get("identifier", ""))
            return {"question": converted_question, "options": converted_options}
        except Exception as exc:
            logger.warning("LatexConverterAgent failed: %s — returning originals", exc)
            return {"question": question, "options": options}


class TrendIntelligenceAgent:
    async def run(self, db: AsyncIOMotorDatabase) -> int:
        repo = RecommenderRepository(db)

        year_matrix = await repo.tool_get_topic_year_matrix()
        if not year_matrix:
            logger.warning("TrendIntelligenceAgent: year matrix is empty")
            return 0

        topic_chapters = {tid: tid.split("::")[0] for tid in year_matrix}
        scorer = TrendScoreComputer(current_year=datetime.now(timezone.utc).year)
        results = scorer.compute_all(year_matrix, topic_chapters)

        updated = 0
        for topic_id, data in results.items():
            await repo.upsert_trend_score(new_topic_trend_doc(
                topic_id=topic_id,
                chapter=data.chapter,
                p_appears=data.p_appears,
                trend_score_raw=data.trend_score_raw,
                gap_bonus=data.gap_bonus,
                streak_score=data.streak_score,
                direction_multiplier=data.direction_multiplier,
            ))
            updated += 1

        asyncio.create_task(self._log_anomalies(results, scorer.high_priority_topics(results)))
        logger.info("TrendIntelligenceAgent: updated %d topics", updated)
        return updated

    async def _log_anomalies(self, results: dict, high_priority: list[str]) -> None:
        try:
            top_5 = sorted(results.values(), key=lambda x: x.p_appears, reverse=True)[:5]
            prompt = (
                f"Top 5 JEE topics by exam appearance probability:\n"
                f"{json.dumps([{'topic_id': d.topic_id, 'p_appears': d.p_appears, 'gap_bonus': d.gap_bonus} for d in top_5], indent=2)}\n\n"
                f"High-priority topics (p > 0.7): {len(high_priority)}\n\n"
                "In 1-2 sentences, flag any surprising trends for exam prep."
            )
            note = await chat_json(
                prompt,
                model=settings.RECOMMENDER_MODEL_FAST,
                system="You are a JEE exam trend analyst. Be concise.",
                temperature=0.3,
                max_tokens=128,
            )
            logger.info("Trend anomaly note: %s", note.strip())
        except Exception as exc:
            logger.debug("Trend anomaly logging skipped: %s", exc)
