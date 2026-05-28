"""
Agent tool wrappers for the JEE Recommender agentic layer.

Each tool is a thin async function that:
  1. Accepts (db, **kwargs) matching the Groq tool parameter schema.
  2. Calls the appropriate RecommenderRepository method.
  3. Returns a JSON-serializable dict.

Three sets of tool definitions (Groq JSON schema format) are exported:

  SESSION_PLANNER_TOOLS   — used by SessionPlannerAgent
  QUESTION_SELECTOR_TOOLS — used by QuestionSelectorAgent
  DIAGNOSIS_TOOLS         — used by DiagnosisAgent

The tool_executor passed to groq_client.chat_with_tools dispatches by name
to the functions defined here.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from modules.recommender.repository import RecommenderRepository


# ---------------------------------------------------------------------------
# Tool executor factory
# ---------------------------------------------------------------------------

def make_tool_executor(db: AsyncIOMotorDatabase, student_id: str):
    """
    Return a coroutine callable(tool_name, args) → dict for the Groq tool loop.

    The student_id is baked in because every tool implicitly operates on one
    student's data. The db is captured from the request context.
    """
    repo = RecommenderRepository(db)

    async def execute(tool_name: str, args: dict[str, Any]) -> Any:
        """Dispatch tool_name to the matching repository method."""

        # ---- Session Planner tools ----
        if tool_name == "get_unlocked_topics":
            return await repo.tool_get_unlocked_topics(student_id)

        if tool_name == "get_due_reviews":
            limit = int(args.get("limit", 5))
            return await repo.tool_get_due_reviews(student_id, limit=limit)

        if tool_name == "get_weakest_unlocked":
            limit = int(args.get("limit", 5))
            return await repo.tool_get_weakest_unlocked(student_id, limit=limit)

        if tool_name == "get_trend_top_topics":
            limit = int(args.get("limit", 10))
            return await repo.tool_get_trend_top_topics(limit=limit)

        # ---- Question Selector tools ----
        if tool_name == "get_candidate_questions":
            return await repo.tool_get_candidate_questions(
                topic_id=args["topic_id"],
                difficulty_min=float(args.get("difficulty_min", -1.5)),
                difficulty_max=float(args.get("difficulty_max", 1.5)),
                exclude_ids=args.get("exclude_seen_correct", []),
                limit=int(args.get("limit", 10)),
            )

        if tool_name == "get_question_type_weights":
            return await repo.tool_get_question_type_weights(student_id)

        # ---- Diagnosis Agent tools ----
        if tool_name == "get_topic_attempt_stats":
            topic_ids = args.get("topic_ids", [])
            return await repo.tool_get_topic_attempt_stats(student_id, topic_ids)

        if tool_name == "get_error_clusters":
            n_recent = int(args.get("n_recent", 30))
            return await repo.tool_get_error_clusters(student_id, n_recent=n_recent)

        if tool_name == "get_session_summary":
            session_id = args.get("session_id", "")
            return await repo.get_session_summary_by_id(session_id) or {}

        if tool_name == "update_student_personality":
            updates = args.get("updates", {})
            await repo.update_personality(student_id, updates)
            return {"status": "updated"}

        if tool_name == "flag_prerequisite_gap":
            await repo.tool_flag_prerequisite_gap(
                student_id=student_id,
                topic_id=args.get("topic_id", ""),
                gap_type=args.get("gap_type", "conceptual_gap"),
            )
            return {"status": "flagged"}

        return {"error": f"Unknown tool: {tool_name}"}

    return execute


# ---------------------------------------------------------------------------
# Groq tool definitions — Session Planner Agent
# ---------------------------------------------------------------------------

SESSION_PLANNER_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_unlocked_topics",
            "description": (
                "Get all unlocked topics for the student with their current mastery stats "
                "and exam appearance probability. Use this to understand which topics the "
                "student can access and where they need the most work."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_due_reviews",
            "description": (
                "Get questions that are due for spaced-repetition review today. "
                "These should be injected into the session to prevent forgetting."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of due reviews to return (default 5).",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weakest_unlocked",
            "description": (
                "Get the topic_ids of the weakest unlocked topics (lowest mastery mean). "
                "Use this to identify which topics need the most drilling."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of weakest topics to return (default 5).",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trend_top_topics",
            "description": (
                "Get the top topics by JEE exam appearance probability (p_appears). "
                "Use this to ensure the session focuses on high-relevance topics."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of top trending topics to return (default 10).",
                    }
                },
                "required": [],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Groq tool definitions — Question Selector Agent
# ---------------------------------------------------------------------------

QUESTION_SELECTOR_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_candidate_questions",
            "description": (
                "Get candidate questions for a specific topic within a difficulty range. "
                "Returns metadata (difficulty, year, type, novelty) without question content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic_id": {
                        "type": "string",
                        "description": "Topic ID in chapter::topic format.",
                    },
                    "difficulty_min": {
                        "type": "number",
                        "description": "Minimum difficulty on the IRT scale (-1=easy, 0=medium, +1=hard).",
                    },
                    "difficulty_max": {
                        "type": "number",
                        "description": "Maximum difficulty on the IRT scale.",
                    },
                    "exclude_seen_correct": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Question IDs the student has already answered correctly (exclude these).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum candidates to return (default 10).",
                    },
                },
                "required": ["topic_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_question_type_weights",
            "description": (
                "Get the student's per-question-type improvement priority weights. "
                "Higher weight means the student needs more practice of that type."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


# ---------------------------------------------------------------------------
# Groq tool definitions — Diagnosis Agent
# ---------------------------------------------------------------------------

DIAGNOSIS_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_topic_attempt_stats",
            "description": (
                "Get detailed attempt statistics for specific topics including "
                "inconsistency rate, difficulty ceiling, and time z-score for error diagnosis."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of topic IDs to analyze.",
                    }
                },
                "required": ["topic_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_error_clusters",
            "description": (
                "Get the dominant error type per topic from recent attempts. "
                "Returns computation|conceptual|application|speed classification per topic."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "n_recent": {
                        "type": "integer",
                        "description": "Number of recent answers to analyze (default 30).",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_session_summary",
            "description": "Get the summary of a specific session by session_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "The session ID to fetch the summary for.",
                    }
                },
                "required": ["session_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_student_personality",
            "description": (
                "Update specific fields of the student personality document. "
                "Use this to record new diagnoses, update error profiles, notes, "
                "confidence profile, or any other personality field."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "updates": {
                        "type": "object",
                        "description": (
                            "Dictionary of fields to update. Valid top-level fields: "
                            "learning_style, fatigue_threshold_questions, confidence_profile, "
                            "improvement_rate, strong_chapters, persistent_weak_chapters, "
                            "avoidance_topics, question_type_strengths, error_profile, notes."
                        ),
                    }
                },
                "required": ["updates"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "flag_prerequisite_gap",
            "description": (
                "Flag a topic as having a specific type of gap. "
                "This adds the topic to the appropriate list in the student's personality "
                "so the Session Planner can prioritize it next session."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic_id": {
                        "type": "string",
                        "description": "The topic ID with the gap.",
                    },
                    "gap_type": {
                        "type": "string",
                        "enum": ["conceptual_gap", "needs_more_drill", "avoidance_detected"],
                        "description": "The type of gap detected.",
                    },
                },
                "required": ["topic_id", "gap_type"],
            },
        },
    },
]
