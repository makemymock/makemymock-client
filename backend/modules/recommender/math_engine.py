"""
Pure-Python math engine for the JEE Recommender.

Contains five independent components, all synchronous and I/O-free:

  IRTEngine            — 1-PL Item Response Theory (§3.2)
  ThompsonSampler      — Beta-posterior topic selection (§3.3)
  SM2Scheduler         — Spaced repetition with SM-2 variant (§3.4)
  PrerequisiteChecker  — Dependency-graph unlock logic (§3.5)
  ConfidenceRegulator  — Rule-based session mode control (§4.6)
  ErrorTaxonomyComputer — Per-topic error classification (§1.1)

None of these classes perform any database I/O. They consume pre-fetched data
and return value objects. This keeps them testable in isolation and fast enough
to run in the per-question hot path (< 5 ms combined).
"""

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


# ---------------------------------------------------------------------------
# Value objects returned by math functions
# ---------------------------------------------------------------------------

@dataclass
class IRTUpdate:
    """Result of one IRT update step."""
    theta_new: float
    p_correct_before: float


@dataclass
class SM2Update:
    """Result of one SM-2 scheduling step."""
    interval_days: int
    easiness_factor: float
    next_review_date: str   # ISO-8601 date string


@dataclass
class SessionModeResult:
    """
    Decision returned by the Confidence Regulator.

    mode            — governs question difficulty and topic selection.
    difficulty_offset — added to the IRT target difficulty.
    topic_override  — if non-None, overrides Thompson Sampling topic choice.
    """
    mode: Literal["normal", "recovery", "wind_down"]
    difficulty_offset: float
    topic_override: Literal["pick_mastered_topic"] | None = None
    prefer_review: bool = False


# ---------------------------------------------------------------------------
# IRTEngine — §3.2
# ---------------------------------------------------------------------------

class IRTEngine:
    """
    1-Parameter Logistic Item Response Theory engine.

    Models student ability (θ) and question difficulty (b) on the same scale.
    After each answer, θ shifts toward the correct ability estimate using a
    gradient-descent-style update with a fixed learning rate η.

    Difficulty mapping (stored in MongoDB):
      easy   → b = -1.0
      medium → b =  0.0
      hard   → b = +1.0
    """

    # P(correct | θ, b) = 1 / (1 + exp(-(θ - b)))
    @staticmethod
    def p_correct(theta: float, difficulty: float) -> float:
        """Probability that a student with ability θ answers a question of difficulty b correctly."""
        return 1.0 / (1.0 + math.exp(-(theta - difficulty)))

    @staticmethod
    def update_theta(theta: float, difficulty: float, correct: bool) -> IRTUpdate:
        """
        Update the student's ability estimate after answering a question.

        Uses the gradient-descent rule:
          θ_new = θ + η × (outcome − P(correct | θ, b))
        """
        p = IRTEngine.p_correct(theta, difficulty)
        outcome = 1.0 if correct else 0.0
        theta_new = theta + IRT_LEARNING_RATE * (outcome - p)
        return IRTUpdate(theta_new=theta_new, p_correct_before=p)

    @staticmethod
    def target_difficulty(theta: float, offset: float = 0.0) -> float:
        """
        Compute the ideal difficulty for the next question.

        b* = θ + ZPD_OFFSET + offset
        At offset=0, this targets P(correct) ≈ 0.65 — the zone of proximal
        development where learning is maximized.
        """
        return theta + IRT_ZPD_OFFSET + offset

    @staticmethod
    def difficulty_band(target: float, half_width: float = 0.4) -> tuple[float, float]:
        """Return the [min, max] difficulty window centered on the target."""
        return (target - half_width, target + half_width)

    @staticmethod
    def str_to_difficulty(difficulty_str: str) -> float:
        """Convert catalog difficulty string to IRT scale float."""
        mapping = {"easy": -1.0, "medium": 0.0, "hard": 1.0}
        return mapping.get(difficulty_str.lower(), 0.0)


# ---------------------------------------------------------------------------
# ThompsonSampler — §3.3
# ---------------------------------------------------------------------------

class ThompsonSampler:
    """
    Thompson Sampling for topic selection via Beta-posterior draws.

    For each unlocked topic, we draw a mastery sample from Beta(α, β).
    Lower mastery samples AND higher exam-appearance probabilities → higher
    priority. The topic with the highest priority is selected.

    This naturally balances exploration (uncertain topics) and exploitation
    (known weak topics) without hand-tuned α, β, γ weights.
    """

    @staticmethod
    def sample_mastery(alpha: int, beta_val: int) -> float:
        """Draw one mastery sample from Beta(alpha, beta_val)."""
        return random.betavariate(alpha, beta_val)

    @staticmethod
    def mastery_mean(alpha: int, beta_val: int) -> float:
        """Point estimate of mastery: α / (α + β)."""
        return alpha / (alpha + beta_val)

    @staticmethod
    def mastery_uncertainty(alpha: int, beta_val: int) -> float:
        """Variance of the Beta posterior — high when few observations."""
        a, b = alpha, beta_val
        return (a * b) / ((a + b) ** 2 * (a + b + 1))

    @staticmethod
    def select_topic(
        topic_states: list[dict[str, Any]],
        trend_scores: dict[str, float],
        focus_topics: list[str] | None = None,
    ) -> str | None:
        """
        Select the highest-priority topic using Thompson Sampling.

        priority[t] = (1 − mastery_sample[t]) × p_appears[t]

        Parameters
        ----------
        topic_states : list of topic state dicts with keys alpha, beta, topic_id.
        trend_scores : mapping topic_id → p_appears (from topic_trend_scores).
        focus_topics : if provided, only consider these topics.

        Returns the topic_id of the selected topic, or None if no candidates.
        """
        candidates = topic_states
        if focus_topics:
            focus_set = set(focus_topics)
            candidates = [s for s in topic_states if s["topic_id"] in focus_set]
        if not candidates:
            candidates = topic_states  # fallback to all unlocked

        best_topic: str | None = None
        best_priority: float = -1.0

        for state in candidates:
            tid = state["topic_id"]
            sample = ThompsonSampler.sample_mastery(state["alpha"], state["beta"])
            p_appears = trend_scores.get(tid, 0.5)  # default 0.5 if trend not yet computed
            priority = (1.0 - sample) * p_appears
            if priority > best_priority:
                best_priority = priority
                best_topic = tid

        return best_topic


# ---------------------------------------------------------------------------
# SM2Scheduler — §3.4
# ---------------------------------------------------------------------------

class SM2Scheduler:
    """
    SM-2 spaced-repetition scheduler (modified variant).

    Grade scale:
      5 — fast and correct (below-average time, right answer)
      4 — slow but correct (above-average time, right answer)
      3 — correct with effort (above-average time, near guess probability)
      0 — wrong answer (any time)

    On correct: interval scales by easiness_factor (EF).
    On wrong: interval resets to 1 day, EF decreases.
    """

    @staticmethod
    def compute_grade(
        correct: bool,
        time_ms: int,
        avg_time_ms: int,
    ) -> int:
        """
        Compute SM-2 grade (0–5) from answer outcome and response time.

        The grade drives EF adjustment. Fast+correct = 5, slow+correct = 4,
        wrong = 0. Grade 3 is not emitted here — it would require a confidence
        self-report which we don't collect.
        """
        if not correct:
            return 0
        if time_ms <= avg_time_ms:
            return 5   # fast and correct
        return 4       # slow but correct

    @staticmethod
    def update_schedule(
        current_interval: int,
        current_ef: float,
        correct: bool,
        grade: int,
        is_first_correct: bool = False,
    ) -> SM2Update:
        """
        Compute new interval and EF after an answer.

        On correct:
          first correct → interval = 1 day
          subsequent   → interval = prev_interval × EF
          EF updated   → EF = max(1.3, EF + 0.1 − (5−grade) × (0.08 + (5−grade) × 0.02))

        On wrong:
          interval resets to 1 day
          EF decreases → EF = max(1.3, EF − 0.2)
        """
        if not correct:
            new_ef = max(SM2_MIN_EASINESS_FACTOR, current_ef - 0.2)
            new_interval = SM2_FIRST_INTERVAL_DAYS
        else:
            if is_first_correct:
                new_interval = SM2_FIRST_INTERVAL_DAYS
            else:
                new_interval = max(1, round(current_interval * current_ef))
            ef_delta = 0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02)
            new_ef = max(SM2_MIN_EASINESS_FACTOR, current_ef + ef_delta)

        next_date = (date.today() + timedelta(days=new_interval)).isoformat()
        return SM2Update(
            interval_days=new_interval,
            easiness_factor=round(new_ef, 3),
            next_review_date=next_date,
        )

    @staticmethod
    def is_due(next_review_date: str) -> bool:
        """Return True if the topic's next review date is today or in the past."""
        try:
            review = date.fromisoformat(next_review_date)
        except ValueError:
            return False
        return date.today() >= review

    @staticmethod
    def should_inject_review(injection_rate: float = SM2_REVIEW_INJECTION_PROB) -> bool:
        """Probabilistic gate: inject a review question this slot."""
        return random.random() < injection_rate


# ---------------------------------------------------------------------------
# PrerequisiteChecker — §3.5
# ---------------------------------------------------------------------------

class PrerequisiteChecker:
    """
    Checks topic unlock status against the prerequisite dependency graph.

    The graph is loaded from prereqs_math.json at startup and passed into
    every check call. No I/O happens inside this class.
    """

    @staticmethod
    def mastery_mean(alpha: int, beta_val: int) -> float:
        """Point estimate of mastery."""
        return alpha / (alpha + beta_val)

    @staticmethod
    def is_unlocked(
        topic_id: str,
        topic_states: dict[str, dict[str, Any]],
        prereq_graph: dict[str, dict[str, Any]],
    ) -> bool:
        """
        Return True if all prerequisites of topic_id are mastered (mean ≥ threshold).

        A topic with no prerequisites is always unlocked. A topic absent from
        the graph is treated as unlocked (defensive fallback).
        """
        node = prereq_graph.get(topic_id)
        if node is None:
            return True
        prereqs: list[str] = node.get("requires", [])
        if not prereqs:
            return True
        for prereq_id in prereqs:
            state = topic_states.get(prereq_id)
            if state is None:
                # Prerequisite not in student's state → treat as not mastered.
                return False
            mean = PrerequisiteChecker.mastery_mean(state["alpha"], state["beta"])
            if mean < MASTERY_THRESHOLD:
                return False
        return True

    @staticmethod
    def get_unlocked_set(
        topic_states: dict[str, dict[str, Any]],
        prereq_graph: dict[str, dict[str, Any]],
    ) -> set[str]:
        """Return the set of all currently unlocked topic_ids for a student."""
        return {
            tid
            for tid in topic_states
            if PrerequisiteChecker.is_unlocked(tid, topic_states, prereq_graph)
        }

    @staticmethod
    def get_newly_unlocked(
        updated_topic_id: str,
        topic_states: dict[str, dict[str, Any]],
        prereq_graph: dict[str, dict[str, Any]],
    ) -> list[str]:
        """
        After updating updated_topic_id's state, return topics that just became unlocked.

        Only checks topics that list updated_topic_id as a direct prerequisite,
        avoiding a full O(n) scan each call.
        """
        dependents = [
            tid
            for tid, node in prereq_graph.items()
            if updated_topic_id in node.get("requires", [])
        ]
        newly_unlocked = []
        for dep_id in dependents:
            state = topic_states.get(dep_id)
            if state is None:
                continue
            # Was locked before the update? (updated topic's old mastery < threshold)
            # We check if it's unlocked NOW; the caller already wrote the new state.
            if PrerequisiteChecker.is_unlocked(dep_id, topic_states, prereq_graph):
                newly_unlocked.append(dep_id)
        return newly_unlocked


# ---------------------------------------------------------------------------
# ConfidenceRegulator — §4.6
# ---------------------------------------------------------------------------

class ConfidenceRegulator:
    """
    Rule-based session mode controller. No LLM. Runs synchronously in the hot path.

    Detects two adverse states:
      Frustration — too many consecutive wrong answers → recovery mode.
      Fatigue     — too many questions served → wind-down mode.

    The thresholds adapt to the student's confidence profile (brittle vs normal).
    """

    @staticmethod
    def get_session_mode(
        consecutive_wrong: int,
        questions_asked: int,
        confidence_profile: str,
        fatigue_threshold: int,
    ) -> SessionModeResult:
        """
        Decide the current session mode based on in-session counters.

        Brittle students hit frustration earlier (after 2 consecutive wrong vs 3).
        All students wind down after their personal fatigue threshold.
        """
        frustration_threshold = (
            REGULATOR_BRITTLE_FRUSTRATION_THRESHOLD
            if confidence_profile == "brittle"
            else REGULATOR_NORMAL_FRUSTRATION_THRESHOLD
        )

        if consecutive_wrong >= frustration_threshold:
            return SessionModeResult(
                mode="recovery",
                difficulty_offset=REGULATOR_RECOVERY_DIFFICULTY_OFFSET,
                topic_override="pick_mastered_topic",
            )

        if questions_asked > fatigue_threshold:
            return SessionModeResult(
                mode="wind_down",
                difficulty_offset=REGULATOR_FATIGUE_DIFFICULTY_OFFSET,
                prefer_review=True,
            )

        return SessionModeResult(mode="normal", difficulty_offset=0.0)


# ---------------------------------------------------------------------------
# ErrorTaxonomyComputer — §1.1
# ---------------------------------------------------------------------------

class ErrorTaxonomyComputer:
    """
    Classifies a student's dominant error type for a given topic.

    Three signals are computed from raw attempt data:
      inconsistency_rate  → high → computation errors (sometimes right, sometimes wrong)
      difficulty_ceiling  → low  → conceptual gap (can't get past medium difficulty)
      time_z_score        → high → speed problem (correct but too slow)

    Classification is hierarchical: speed is checked last because it often
    co-occurs with other error types.
    """

    @staticmethod
    def compute_inconsistency_rate(outcomes: list[bool]) -> float:
        """
        std(binary_outcomes) / mean(binary_outcomes).

        High value → student is inconsistent within the topic → computation errors.
        Returns 0.0 if fewer than 3 attempts or all outcomes are the same.
        """
        if len(outcomes) < 3:
            return 0.0
        n = len(outcomes)
        mean = sum(outcomes) / n
        if mean == 0.0 or mean == 1.0:
            return 0.0
        variance = sum((x - mean) ** 2 for x in outcomes) / n
        std = math.sqrt(variance)
        return std / mean

    @staticmethod
    def compute_difficulty_ceiling(
        difficulties: list[float],
        outcomes: list[bool],
    ) -> float:
        """
        Max difficulty of questions where the student's success rate > 0.5.

        Low ceiling → student cannot progress past easy/medium → conceptual gap.
        Returns -2.0 (below easy) if they have no correct answers at all.
        """
        if not difficulties or not outcomes:
            return -2.0
        # Group by difficulty and compute P(correct)
        groups: dict[float, list[bool]] = {}
        for d, o in zip(difficulties, outcomes):
            groups.setdefault(d, []).append(o)

        ceiling = -2.0
        for d, outs in groups.items():
            p_correct = sum(outs) / len(outs)
            if p_correct > 0.5 and d > ceiling:
                ceiling = d
        return ceiling

    @staticmethod
    def compute_time_z_score(
        student_avg_ms: float,
        pop_mean_ms: float,
        pop_std_ms: float,
    ) -> float:
        """
        Standardized time deviation: (student_avg − pop_mean) / pop_std.

        High z-score → student takes significantly longer than peers → speed problem.
        Returns 0.0 if std is zero (no variance in population data).
        """
        if pop_std_ms == 0.0:
            return 0.0
        return (student_avg_ms - pop_mean_ms) / pop_std_ms

    @staticmethod
    def classify_error_type(
        inconsistency_rate: float,
        difficulty_ceiling: float,
        time_z_score: float,
    ) -> Literal["computation", "conceptual", "application", "speed", "none"]:
        """
        Map the three signals to one dominant error type.

        Priority order: conceptual > computation > application > speed > none.
        Conceptual is prioritized because it requires the most intervention.
        """
        if difficulty_ceiling < ERROR_CEILING_LOW:
            return "conceptual"
        if inconsistency_rate > ERROR_INCONSISTENCY_HIGH:
            return "computation"
        # Application: correct on easy, wrong on hard (ceiling just above medium)
        if 0.0 <= difficulty_ceiling <= 0.3:
            return "application"
        if time_z_score > ERROR_TIME_Z_HIGH:
            return "speed"
        return "none"

    @staticmethod
    def compute_avoidance_score(accuracy: float, time_z_score: float) -> float:
        """
        avoidance_score = (1 − accuracy) × (1 / max(time_z, 0.1))

        High score → student answers quickly AND incorrectly → likely guessing to skip.
        Guarding against division by zero with max(time_z, 0.1).
        """
        return (1.0 - accuracy) * (1.0 / max(time_z_score, 0.1))
