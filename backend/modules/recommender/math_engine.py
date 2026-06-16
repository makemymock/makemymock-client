from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from modules.recommender.constants import (
    ERROR_CEILING_LOW,
    ERROR_INCONSISTENCY_HIGH,
    ERROR_TIME_Z_HIGH,
    IRT_LEARNING_RATE,
    IRT_ZPD_OFFSET,
    MASTERY_THRESHOLD,
    REGULATOR_BRITTLE_FRUSTRATION_THRESHOLD,
    REGULATOR_FATIGUE_DIFFICULTY_OFFSET,
    REGULATOR_NORMAL_FRUSTRATION_THRESHOLD,
    REGULATOR_RECOVERY_DIFFICULTY_OFFSET,
    SM2_DEFAULT_EASINESS_FACTOR,
    SM2_FIRST_INTERVAL_DAYS,
    SM2_MIN_EASINESS_FACTOR,
    SM2_REVIEW_INJECTION_PROB,
)


@dataclass
class IRTUpdate:
    theta_new: float
    p_correct_before: float


@dataclass
class SM2Update:
    interval_days: int
    easiness_factor: float
    next_review_date: str


@dataclass
class SessionModeResult:
    mode: Literal["normal", "recovery", "wind_down"]
    difficulty_offset: float
    topic_override: Literal["pick_mastered_topic"] | None = None
    prefer_review: bool = False


class IRTEngine:
    @staticmethod
    def p_correct(theta: float, difficulty: float) -> float:
        return 1.0 / (1.0 + math.exp(-(theta - difficulty)))

    @staticmethod
    def update_theta(theta: float, difficulty: float, correct: bool) -> IRTUpdate:
        p = IRTEngine.p_correct(theta, difficulty)
        theta_new = theta + IRT_LEARNING_RATE * ((1.0 if correct else 0.0) - p)
        return IRTUpdate(theta_new=theta_new, p_correct_before=p)

    @staticmethod
    def target_difficulty(theta: float, offset: float = 0.0) -> float:
        return theta + IRT_ZPD_OFFSET + offset

    @staticmethod
    def difficulty_band(target: float, half_width: float = 0.4) -> tuple[float, float]:
        return (target - half_width, target + half_width)

    @staticmethod
    def str_to_difficulty(difficulty_str: str) -> float:
        return {"easy": -1.0, "medium": 0.0, "hard": 1.0}.get(difficulty_str.lower(), 0.0)


class ThompsonSampler:
    @staticmethod
    def sample_mastery(alpha: int, beta_val: int) -> float:
        return random.betavariate(alpha, beta_val)

    @staticmethod
    def mastery_mean(alpha: int, beta_val: int) -> float:
        return alpha / (alpha + beta_val)

    @staticmethod
    def mastery_uncertainty(alpha: int, beta_val: int) -> float:
        a, b = alpha, beta_val
        return (a * b) / ((a + b) ** 2 * (a + b + 1))

    @staticmethod
    def select_topic(
        topic_states: list[dict[str, Any]],
        trend_scores: dict[str, float],
        focus_topics: list[str] | None = None,
    ) -> str | None:
        candidates = topic_states
        if focus_topics:
            focus_set = set(focus_topics)
            candidates = [s for s in topic_states if s["topic_id"] in focus_set]
        if not candidates:
            candidates = topic_states

        best_topic: str | None = None
        best_priority = -1.0
        for state in candidates:
            tid = state["topic_id"]
            sample = ThompsonSampler.sample_mastery(state["alpha"], state["beta"])
            priority = (1.0 - sample) * trend_scores.get(tid, 0.5)
            if priority > best_priority:
                best_priority = priority
                best_topic = tid
        return best_topic


class SM2Scheduler:
    @staticmethod
    def compute_grade(correct: bool, time_ms: int, avg_time_ms: int) -> int:
        if not correct: return 0
        return 5 if time_ms <= avg_time_ms else 4

    @staticmethod
    def update_schedule(
        current_interval: int,
        current_ef: float,
        correct: bool,
        grade: int,
        is_first_correct: bool = False,
    ) -> SM2Update:
        if not correct:
            new_ef = max(SM2_MIN_EASINESS_FACTOR, current_ef - 0.2)
            new_interval = SM2_FIRST_INTERVAL_DAYS
        else:
            new_interval = SM2_FIRST_INTERVAL_DAYS if is_first_correct else max(1, round(current_interval * current_ef))
            ef_delta = 0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02)
            new_ef = max(SM2_MIN_EASINESS_FACTOR, current_ef + ef_delta)
        next_date = (date.today() + timedelta(days=new_interval)).isoformat()
        return SM2Update(interval_days=new_interval, easiness_factor=round(new_ef, 3), next_review_date=next_date)

    @staticmethod
    def is_due(next_review_date: str) -> bool:
        try:
            return date.today() >= date.fromisoformat(next_review_date)
        except ValueError:
            return False

    @staticmethod
    def should_inject_review(injection_rate: float = SM2_REVIEW_INJECTION_PROB) -> bool:
        return random.random() < injection_rate


class PrerequisiteChecker:
    @staticmethod
    def mastery_mean(alpha: int, beta_val: int) -> float:
        return alpha / (alpha + beta_val)

    @staticmethod
    def is_unlocked(topic_id: str, topic_states: dict[str, dict], prereq_graph: dict[str, dict]) -> bool:
        node = prereq_graph.get(topic_id)
        if node is None:
            return True
        prereqs: list[str] = node.get("requires", [])
        if not prereqs:
            return True
        for prereq_id in prereqs:
            state = topic_states.get(prereq_id)
            if state is None:
                return False
            if PrerequisiteChecker.mastery_mean(state["alpha"], state["beta"]) < MASTERY_THRESHOLD:
                return False
        return True

    @staticmethod
    def get_unlocked_set(topic_states: dict[str, dict], prereq_graph: dict[str, dict]) -> set[str]:
        return {tid for tid in topic_states if PrerequisiteChecker.is_unlocked(tid, topic_states, prereq_graph)}

    @staticmethod
    def get_newly_unlocked(updated_topic_id: str, topic_states: dict[str, dict], prereq_graph: dict[str, dict]) -> list[str]:
        dependents = [tid for tid, node in prereq_graph.items() if updated_topic_id in node.get("requires", [])]
        return [
            dep_id for dep_id in dependents
            if topic_states.get(dep_id) and PrerequisiteChecker.is_unlocked(dep_id, topic_states, prereq_graph)
        ]


class ConfidenceRegulator:
    @staticmethod
    def get_session_mode(
        consecutive_wrong: int,
        questions_asked: int,
        confidence_profile: str,
        fatigue_threshold: int,
    ) -> SessionModeResult:
        threshold = (
            REGULATOR_BRITTLE_FRUSTRATION_THRESHOLD
            if confidence_profile == "brittle"
            else REGULATOR_NORMAL_FRUSTRATION_THRESHOLD
        )
        if consecutive_wrong >= threshold:
            return SessionModeResult(
                mode="recovery",
                difficulty_offset=REGULATOR_RECOVERY_DIFFICULTY_OFFSET,
                topic_override="pick_mastered_topic",
            )
        if questions_asked > fatigue_threshold:
            return SessionModeResult(mode="wind_down", difficulty_offset=REGULATOR_FATIGUE_DIFFICULTY_OFFSET, prefer_review=True)
        return SessionModeResult(mode="normal", difficulty_offset=0.0)


class ErrorTaxonomyComputer:
    @staticmethod
    def compute_inconsistency_rate(outcomes: list[bool]) -> float:
        if len(outcomes) < 3: return 0.0
        n = len(outcomes)
        mean = sum(outcomes) / n
        if mean == 0.0 or mean == 1.0: return 0.0
        variance = sum((x - mean) ** 2 for x in outcomes) / n
        return math.sqrt(variance) / mean

    @staticmethod
    def compute_difficulty_ceiling(difficulties: list[float], outcomes: list[bool]) -> float:
        if not difficulties or not outcomes: return -2.0
        groups: dict[float, list[bool]] = {}
        for d, o in zip(difficulties, outcomes):
            groups.setdefault(d, []).append(o)
        ceiling = -2.0
        for d, outs in groups.items():
            if sum(outs) / len(outs) > 0.5 and d > ceiling:
                ceiling = d
        return ceiling

    @staticmethod
    def compute_time_z_score(student_avg_ms: float, pop_mean_ms: float, pop_std_ms: float) -> float:
        if pop_std_ms == 0.0: return 0.0
        return (student_avg_ms - pop_mean_ms) / pop_std_ms

    @staticmethod
    def classify_error_type(
        inconsistency_rate: float,
        difficulty_ceiling: float,
        time_z_score: float,
    ) -> Literal["computation", "conceptual", "application", "speed", "none"]:
        if difficulty_ceiling < ERROR_CEILING_LOW: return "conceptual"
        if inconsistency_rate > ERROR_INCONSISTENCY_HIGH: return "computation"
        if 0.0 <= difficulty_ceiling <= 0.3: return "application"
        if time_z_score > ERROR_TIME_Z_HIGH: return "speed"
        return "none"

    @staticmethod
    def compute_avoidance_score(accuracy: float, time_z_score: float) -> float:
        return (1.0 - accuracy) * (1.0 / max(time_z_score, 0.1))
