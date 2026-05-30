from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from modules.recommender.constants import (
    DEFAULT_CONFIDENCE_PROFILE,
    DEFAULT_FATIGUE_THRESHOLD,
    DEFAULT_IMPROVEMENT_RATE,
    DEFAULT_LEARNING_STYLE,
    INCORRECT_FIRST_INTERVAL_DAYS,
    SM2_DEFAULT_EASINESS_FACTOR,
    SM2_FIRST_INTERVAL_DAYS,
    SUBJECT_MATHEMATICS,
    THOMPSON_INITIAL_ALPHA,
    THOMPSON_INITIAL_BETA,
)


def _utcnow() -> datetime: return datetime.now(timezone.utc)
def _today_iso() -> str: return date.today().isoformat()


def new_student_topic_state_doc(
    student_id: str, topic_id: str, chapter: str,
    subject: str = SUBJECT_MATHEMATICS,
) -> dict[str, Any]:
    return {
        "student_id": student_id,
        "topic_id": topic_id,
        "chapter": chapter,
        "subject": subject,
        "alpha": THOMPSON_INITIAL_ALPHA,
        "beta": THOMPSON_INITIAL_BETA,
        "theta": 0.0,
        "next_review_date": _today_iso(),
        "review_interval_days": SM2_FIRST_INTERVAL_DAYS,
        "easiness_factor": SM2_DEFAULT_EASINESS_FACTOR,
        "total_attempts": 0,
        "total_correct": 0,
        "last_attempted": None,
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
    }


def new_student_personality_doc(student_id: str) -> dict[str, Any]:
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


def new_question_history_doc(
    student_id: str, session_id: str, question_id: str,
    topic_id: str, chapter: str, correct: bool,
    time_ms: int, difficulty: float, question_type: str,
) -> dict[str, Any]:
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


def new_session_summary_doc(
    session_id: str, student_id: str, duration_minutes: float,
    questions_attempted: int, accuracy_by_chapter: dict[str, float],
    avg_time_by_topic: dict[str, float], frustration_events_count: int,
    topics_unlocked: list[str], first_half_accuracy: float,
    second_half_accuracy: float, hardest_correct_difficulty: float | None,
    easiest_wrong_difficulty: float | None, session_mode_sequence: list[str],
) -> dict[str, Any]:
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


def new_solved_question_doc(
    student_id: str, question_id: str, topic_id: str,
    chapter: str, difficulty: float, question_type: str,
    last_correct: bool = True,
    subject: str = SUBJECT_MATHEMATICS,
) -> dict:
    # Correct answers: start SM-2 at 1-day interval.
    # Incorrect answers: also start at 1 day (INCORRECT_FIRST_INTERVAL_DAYS) but flagged.
    interval = SM2_FIRST_INTERVAL_DAYS if last_correct else INCORRECT_FIRST_INTERVAL_DAYS
    return {
        "student_id": student_id,
        "question_id": question_id,
        "topic_id": topic_id,
        "chapter": chapter,
        "subject": subject,
        "difficulty": difficulty,
        "question_type": question_type,
        "last_correct": last_correct,
        "times_attempted": 1,
        "times_correct": 1 if last_correct else 0,
        "consecutive_incorrect": 0 if last_correct else 1,
        "last_attempted_at": _utcnow(),
        "next_review_date": (date.today() + timedelta(days=interval)).isoformat(),
        "review_interval_days": interval,
        "easiness_factor": 2.5,
        "created_at": _utcnow(),
    }


def new_topic_trend_doc(
    topic_id: str, chapter: str, p_appears: float,
    trend_score_raw: float, gap_bonus: float,
    streak_score: float, direction_multiplier: float,
) -> dict[str, Any]:
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
