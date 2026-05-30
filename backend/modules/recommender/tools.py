from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from modules.recommender.repository import RecommenderRepository


def make_tool_executor(db: AsyncIOMotorDatabase, student_id: str):
    repo = RecommenderRepository(db)

    async def execute(tool_name: str, args: dict[str, Any]) -> Any:
        if tool_name == "get_unlocked_topics":
            return await repo.tool_get_unlocked_topics(student_id)

        if tool_name == "get_due_reviews":
            return await repo.tool_get_due_reviews(student_id, limit=int(args.get("limit", 5)))

        if tool_name == "get_weakest_unlocked":
            return await repo.tool_get_weakest_unlocked(student_id, limit=int(args.get("limit", 5)))

        if tool_name == "get_trend_top_topics":
            return await repo.tool_get_trend_top_topics(limit=int(args.get("limit", 10)))

        if tool_name == "get_candidate_questions":
            return await repo.tool_get_candidate_questions(
                topic_id=args["topic_id"],
                difficulty_min=float(args.get("difficulty_min", -1.5)),
                difficulty_max=float(args.get("difficulty_max", 1.5)),
                exclude_ids=args.get("exclude_seen_correct", []),
                limit=int(args.get("limit", 10)),
                student_id=student_id,
            )

        if tool_name == "get_question_type_weights":
            return await repo.tool_get_question_type_weights(student_id)

        if tool_name == "get_topic_attempt_stats":
            return await repo.tool_get_topic_attempt_stats(student_id, args.get("topic_ids", []))

        if tool_name == "get_error_clusters":
            return await repo.tool_get_error_clusters(student_id, n_recent=int(args.get("n_recent", 30)))

        if tool_name == "get_session_summary":
            return await repo.get_session_summary_by_id(args.get("session_id", "")) or {}

        if tool_name == "update_student_personality":
            await repo.update_personality(student_id, args.get("updates", {}))
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


SESSION_PLANNER_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_unlocked_topics",
            "description": "Get all unlocked topics for the student with mastery stats and exam appearance probability.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_due_reviews",
            "description": "Get questions due for spaced-repetition review today.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "description": "Max reviews to return (default 5)."}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weakest_unlocked",
            "description": "Get topic_ids of the weakest unlocked topics (lowest mastery mean).",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "description": "Number of topics to return (default 5)."}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trend_top_topics",
            "description": "Get the top topics by JEE exam appearance probability.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "description": "Number of topics to return (default 10)."}},
                "required": [],
            },
        },
    },
]


QUESTION_SELECTOR_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_candidate_questions",
            "description": "Get candidate questions for a topic within a difficulty range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic_id": {"type": "string", "description": "Topic ID in chapter::topic format."},
                    "difficulty_min": {"type": "number", "description": "Min difficulty on IRT scale (-1=easy, 0=medium, +1=hard)."},
                    "difficulty_max": {"type": "number", "description": "Max difficulty on IRT scale."},
                    "exclude_seen_correct": {"type": "array", "items": {"type": "string"}, "description": "Question IDs to exclude."},
                    "limit": {"type": "integer", "description": "Max candidates to return (default 10)."},
                },
                "required": ["topic_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_question_type_weights",
            "description": "Get the student's per-question-type improvement priority weights.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


DIAGNOSIS_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_topic_attempt_stats",
            "description": "Get attempt stats (inconsistency rate, difficulty ceiling, time z-score) for specific topics.",
            "parameters": {
                "type": "object",
                "properties": {"topic_ids": {"type": "array", "items": {"type": "string"}, "description": "Topic IDs to analyze."}},
                "required": ["topic_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_error_clusters",
            "description": "Get dominant error type per topic from recent attempts (computation|conceptual|application|speed).",
            "parameters": {
                "type": "object",
                "properties": {"n_recent": {"type": "integer", "description": "Number of recent answers to analyze (default 30)."}},
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
                "properties": {"session_id": {"type": "string", "description": "The session ID."}},
                "required": ["session_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_student_personality",
            "description": "Update specific fields of the student personality document.",
            "parameters": {
                "type": "object",
                "properties": {
                    "updates": {
                        "type": "object",
                        "description": "Fields to update: learning_style, fatigue_threshold_questions, confidence_profile, improvement_rate, strong_chapters, persistent_weak_chapters, avoidance_topics, question_type_strengths, error_profile, notes.",
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
            "description": "Flag a topic as having a gap, adding it to the student's avoidance/weak lists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic_id": {"type": "string", "description": "Topic ID with the gap."},
                    "gap_type": {"type": "string", "enum": ["conceptual_gap", "needs_more_drill", "avoidance_detected"], "description": "Type of gap."},
                },
                "required": ["topic_id", "gap_type"],
            },
        },
    },
]
