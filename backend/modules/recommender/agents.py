from __future__ import annotations

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
- confidence_note: speak directly to the student using "you". Name their strongest and weakest topic explicitly. Be warm and motivating — 3-4 sentences. Explain what you found (weakest topic, exam trend, error pattern if known) and what today's session targets. Example: "You've been doing well in Complex Numbers, but Limits is where you're struggling most — your mastery is only 38%. I also noticed that Limits appears in 74% of recent JEE papers, so it's the highest-leverage topic right now. Today's session will focus here, starting comfortable and pushing up as you warm up." """

    _TOOL_LABELS = {
        "get_unlocked_topics":       "Checking your topic map",
        "get_due_reviews":           "Checking spaced-repetition queue",
        "get_weakest_unlocked":      "Identifying weak spots",
        "get_trend_top_topics":      "Checking JEE exam trends",
        "get_candidate_questions":   "Browsing question bank",
        "get_question_type_weights": "Checking question-type priorities",
        "get_topic_attempt_stats":   "Analysing attempt patterns",
        "get_error_clusters":        "Identifying error patterns",
        "get_session_summary":       "Reviewing last session",
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
        # Uses the actual result to produce specific, data-driven labels instead
        # of generic hardcoded strings.
        _seen_count: list[int] = [0]

        async def _on_tool_result(_round_num: int, tool_name: str, _args: dict, result: object) -> None:
            if not on_step:
                return

            label = self._TOOL_LABELS.get(tool_name, tool_name)

            if tool_name == "get_unlocked_topics" and isinstance(result, list):
                n = len(result)
                weakest = next(
                    (r for r in result if isinstance(r, dict) and r.get("mastery_mean", 1.0) < 0.5),
                    result[0] if result else None,
                )
                if weakest and isinstance(weakest, dict):
                    wname = weakest.get("topic_id", "").split("::")[-1].replace("-", " ").title()
                    wm    = int(weakest.get("mastery_mean", 0) * 100)
                    label = f"{n} topics found · weakest: {wname} ({wm}%)"
                else:
                    label = f"{n} topics found"

            elif tool_name == "get_due_reviews" and isinstance(result, list):
                n = len(result)
                label = f"{n} due for review today" if n else "No reviews pending"

            elif tool_name == "get_weakest_unlocked" and isinstance(result, list):
                if result:
                    names = [t.split("::")[-1].replace("-", " ").title() for t in result[:3]]
                    label = f"Weak spots: {', '.join(names)}"
                else:
                    label = "All topics looking strong"

            elif tool_name == "get_trend_top_topics" and isinstance(result, list):
                if result:
                    top2 = [
                        (t.get("topic_id", "").split("::")[-1].replace("-", " ").title(),
                         int(t.get("p_appears", 0) * 100))
                        for t in result[:2]
                    ]
                    label = "High-frequency JEE topics: " + ", ".join(f"{n} ({p}%)" for n, p in top2)
                else:
                    label = "Checking trend data"

            idx = _seen_count[0]
            _seen_count[0] += 1
            await on_step({"type": "step", "tool": tool_name, "label": label, "index": idx})

        async def _on_thought(text: str) -> None:
            if on_step:
                await on_step({"type": "thought", "text": text})

        try:
            final_text, tool_calls = await chat_with_tools(
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                tools=SESSION_PLANNER_TOOLS,
                tool_executor=make_tool_executor(db, student_id),
                model=settings.GEMINI_MODEL_FLASH,
                temperature=0.15,
                max_tokens=2048,
                max_tool_rounds=5,
                thinking_budget=16000,  # noqa: keep high — planner needs deep reasoning
                on_tool_result=_on_tool_result if on_step else None,
                on_thought=_on_thought if on_step else None,
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
    SYSTEM_PROMPT = (
        "You are a JEE question selector.\n\n"
        "Steps:\n"
        "1. Call get_candidate_questions with the topic_id and difficulty range provided.\n"
        "   - If the result is an EMPTY list, immediately respond with "
        "{\"selected_question_id\": null} — do NOT call any more tools.\n"
        "2. Call get_question_type_weights to see which types the student needs most.\n"
        "3. Pick the single best question by: highest type_weight → is_novel=true → most recent year.\n"
        "4. Respond with exactly: {\"selected_question_id\": \"<id>\"}"
    )

    async def run(
        self,
        student_id: str,
        topic_id: str,
        seen_ids: list[str],
        db: AsyncIOMotorDatabase,
        *,
        on_step=None,
    ) -> str | None:
        tool_calls: list[dict] = []
        _idx: list[int] = [0]

        async def _on_tool_result(_rn: int, tool_name: str, _args: dict, result: object) -> None:
            label = tool_name
            if tool_name == "get_candidate_questions":
                n = len(result) if isinstance(result, list) else 0
                if n == 0:
                    return  # 0 candidates means exclusion window is in play — fallback handles it, no need to surface
                label = f"Found {n} candidate question{'s' if n != 1 else ''}"
            elif tool_name == "get_question_type_weights" and isinstance(result, dict):
                try:
                    weakest = max(result.items(), key=lambda x: float(x[1]))[0]
                    label = f"Prioritising {weakest.replace('_', ' ')} — needs the most work"
                except Exception:
                    label = "Checked which question types need the most work"
            if on_step:
                await on_step({"type": "step", "tool": tool_name, "label": label, "index": _idx[0]})
            _idx[0] += 1

        async def _on_selector_thought(text: str) -> None:
            if on_step:
                await on_step({"type": "thought", "text": text})

        try:
            final_text, tool_calls = await chat_with_tools(
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": (
                        f"topic_id: {topic_id}\n"
                        f"exclude_seen_correct: {seen_ids[:30]}"
                    )},
                ],
                tools=QUESTION_SELECTOR_TOOLS,
                tool_executor=make_tool_executor(db, student_id),
                model=settings.GEMINI_MODEL_FLASH,
                temperature=0.05,
                max_tokens=1024,
                max_tool_rounds=3,
                thinking_budget=10000,  # noqa: keep high — selector needs careful reasoning
                on_tool_result=_on_tool_result if on_step else None,
                on_thought=_on_selector_thought if on_step else None,
            )
            start, end = final_text.find("{"), final_text.rfind("}") + 1
            if start != -1 and end > 0:
                qid = json.loads(final_text[start:end]).get("selected_question_id")
                if qid:
                    return str(qid)
        except Exception as exc:
            logger.warning("QuestionSelectorAgent failed: %s", exc)

        # Fallback: first candidate returned by the tool
        for tc in tool_calls:
            if tc["name"] == "get_candidate_questions":
                cands = tc.get("result") or []
                if isinstance(cands, list) and cands:
                    return cands[0].get("question_id")
        return None


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
                model=settings.GEMINI_MODEL_FLASH,
                temperature=0.1,
                max_tokens=2048,
                max_tool_rounds=8,
                thinking_budget=16000,  # noqa: keep high — diagnosis needs deep analysis
            )
            logger.info("DiagnosisAgent done for %s (trigger=%s) tools=%d", student_id, trigger, len(tool_calls))

            # Parse main_finding and persist it so the frontend can surface it
            start, end = final_text.find("{"), final_text.rfind("}") + 1
            if start != -1 and end > 0:
                finding = json.loads(final_text[start:end]).get("main_finding", "")
                if finding:
                    await RecommenderRepository(db).update_personality(
                        student_id, {"last_session_finding": finding}
                    )
                    logger.info("DiagnosisAgent saved main_finding for %s: %.120s", student_id, finding)
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

        year_matrix, topic_subjects = await repo.tool_get_topic_year_matrix()
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
                subject=topic_subjects.get(topic_id, ""),
                p_appears=data.p_appears,
                trend_score_raw=data.trend_score_raw,
                gap_bonus=data.gap_bonus,
                streak_score=data.streak_score,
                direction_multiplier=data.direction_multiplier,
            ))
            updated += 1

        logger.info("TrendIntelligenceAgent: updated %d topics", updated)
        return updated
