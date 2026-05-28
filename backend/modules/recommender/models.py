"""
MongoDB document factories for the JEE Recommender module.

Every document written to Mongo passes through one of these factories so that
field shapes and default values are always consistent across the codebase.
Follow the same convention as other modules: new_*_doc() returns a plain dict
ready for Motor's insert_one / replace_one.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from modules.recommender.constants import (
    DEFAULT_CONFIDENCE_PROFILE,
    DEFAULT_FATIGUE_THRESHOLD,
    DEFAULT_IMPROVEMENT_RATE,
    DEFAULT_LEARNING_STYLE,
    SM2_DEFAULT_EASINESS_FACTOR,
    SM2_FIRST_INTERVAL_DAYS,
    THOMPSON_INITIAL_ALPHA,
    THOMPSON_INITIAL_BETA,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _today_iso() -> str:
    return date.today().isoformat()


# ---------------------------------------------------------------------------
# student_topic_state — one doc per (student_id, topic_id), 156 total per student
# ---------------------------------------------------------------------------

def new_student_topic_state_doc(
    student_id: str,
    topic_id: str,
    chapter: str,
) -> dict[str, Any]:
    """
    Create an initial topic-state document for a student.

    The Beta prior starts at (1, 1) — a uniform distribution over [0, 1]
    mastery. θ (IRT ability) starts at 0.0, which maps to P(correct) = 0.5
    on a medium-difficulty question. SM-2 review starts in 1 day.
    """
    return {
        "student_id": student_id,
        "topic_id": topic_id,
        "chapter": chapter,
        # Thompson Sampling Beta posterior (alpha = successes+1, beta = failures+1)
        "alpha": THOMPSON_INITIAL_ALPHA,
        "beta": THOMPSON_INITIAL_BETA,
        # IRT ability estimate on logistic scale
        "theta": 0.0,
        # Spaced repetition (SM-2)
        "next_review_date": _today_iso(),
        "review_interval_days": SM2_FIRST_INTERVAL_DAYS,
        "easiness_factor": SM2_DEFAULT_EASINESS_FACTOR,
        # Session metadata
        "total_attempts": 0,
        "total_correct": 0,
        "last_attempted": None,
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
    }


# ---------------------------------------------------------------------------
# student_personality — one doc per student, updated after each session
# ---------------------------------------------------------------------------

def new_student_personality_doc(student_id: str) -> dict[str, Any]:
    """
    Create a default personality document for a newly initialized student.

    All fields match the shape described in §1.6 of RECOMMENDER_ARCHITECTURE.md.
    The Diagnosis Agent overwrites individual fields after each session; it never
    replaces the whole document so unrecognized future fields are preserved.
    """
    return {
        "student_id": student_id,
        "learning_style": DEFAULT_LEARNING_STYLE,
        "fatigue_threshold_questions": DEFAULT_FATIGUE_THRESHOLD,
        "confidence_profile": DEFAULT_CONFIDENCE_PROFILE,
        "improvement_rate": DEFAULT_IMPROVEMENT_RATE,
        "strong_chapters": [],
        "persistent_weak_chapters": [],
        "avoidance_topics": [],
        "question_type_strengths": {
            "single_correct": 0.5,
            "multi_correct": 0.5,
            "integer": 0.5,
            "matching": 0.5,
        },
        "error_profile": {},
        "notes": "",
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
    }


# ---------------------------------------------------------------------------
# student_question_history — raw event log, one doc per answer event
# ---------------------------------------------------------------------------

def new_question_history_doc(
    student_id: str,
    session_id: str,
    question_id: str,
    topic_id: str,
    chapter: str,
    correct: bool,
    time_ms: int,
    difficulty: float,
    question_type: str,
) -> dict[str, Any]:
    """
    Create a raw answer event document.

    These are never shown to agents directly (§5.2). All agent context comes
    from aggregated tool calls that query this collection.
    """
    return {
        "student_id": student_id,
        "session_id": session_id,
        "question_id": question_id,
        "topic_id": topic_id,
        "chapter": chapter,
        "correct": correct,
        "time_ms": time_ms,
        "difficulty": difficulty,
        "question_type": question_type,
        "timestamp": _utcnow(),
    }


# ---------------------------------------------------------------------------
# session_summaries — Level-1 memory, generated after each session
# ---------------------------------------------------------------------------

def new_session_summary_doc(
    session_id: str,
    student_id: str,
    duration_minutes: float,
    questions_attempted: int,
    accuracy_by_chapter: dict[str, float],
    avg_time_by_topic: dict[str, float],
    frustration_events_count: int,
    topics_unlocked: list[str],
    first_half_accuracy: float,
    second_half_accuracy: float,
    hardest_correct_difficulty: float | None,
    easiest_wrong_difficulty: float | None,
    session_mode_sequence: list[str],
) -> dict[str, Any]:
    """
    Create a compressed session summary document (≈200 tokens when serialized).

    This is the Level-1 memory layer. The Session Planner agent receives the
    last 3 of these (≈450 tokens total) alongside the personality document.
    """
    return {
        "session_id": session_id,
        "student_id": student_id,
        "duration_minutes": round(duration_minutes, 1),
        "questions_attempted": questions_attempted,
        "accuracy_by_chapter": accuracy_by_chapter,
        "avg_time_by_topic": avg_time_by_topic,
        "frustration_events_count": frustration_events_count,
        "topics_unlocked": topics_unlocked,
        "first_half_accuracy": round(first_half_accuracy, 3),
        "second_half_accuracy": round(second_half_accuracy, 3),
        "hardest_correct_difficulty": hardest_correct_difficulty,
        "easiest_wrong_difficulty": easiest_wrong_difficulty,
        "session_mode_sequence": session_mode_sequence,
        "created_at": _utcnow(),
    }


# ---------------------------------------------------------------------------
# topic_trend_scores — 156 docs, recomputed weekly by Trend Intelligence Agent
# ---------------------------------------------------------------------------

def new_topic_trend_doc(
    topic_id: str,
    chapter: str,
    p_appears: float,
    trend_score_raw: float,
    gap_bonus: float,
    streak_score: float,
    direction_multiplier: float,
) -> dict[str, Any]:
    """
    Create or replace a topic trend score document.

    p_appears is the final sigmoid-normalized probability that this topic
    appears in this year's JEE Mains exam. Used by Thompson Sampling as the
    urgency weight in priority = (1 - mastery_sample) × p_appears.
    """
    return {
        "topic_id": topic_id,
        "chapter": chapter,
        "p_appears": round(p_appears, 4),
        "trend_score_raw": round(trend_score_raw, 4),
        "gap_bonus": round(gap_bonus, 4),
        "streak_score": round(streak_score, 4),
        "direction_multiplier": round(direction_multiplier, 4),
        "computed_at": _utcnow(),
    }
