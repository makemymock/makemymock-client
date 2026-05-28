"""
JEE topic trend score computation pipeline.

Implements the full §2 algorithm from RECOMMENDER_ARCHITECTURE.md:

  1. trend_score_raw  — exponential decay over historical question counts
  2. gap_bonus        — multiplier for topics that are "overdue" (absent recently)
  3. streak_score     — multiplier for topics appearing consecutively
  4. direction_multiplier — nudge based on volume trend (increasing vs declining)
  5. p_appears        — sigmoid-normalized final probability [0, 1]

All methods are stateless and I/O-free. The Trend Intelligence Agent calls
compute_all(), stores the results via the repository, and the recommender reads
p_appears from topic_trend_scores at query time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from modules.recommender.constants import (
    TREND_DECAY_LAMBDA,
    TREND_DIRECTION_FACTOR,
    TREND_DIRECTION_MAX_SLOPE,
    TREND_GAP_BONUS_CAP,
    TREND_GAP_BONUS_PER_YEAR,
    TREND_HIGH_PRIORITY_THRESHOLD,
    TREND_MAX_STREAK_YEARS,
    TREND_SIGMOID_SHARPNESS,
    TREND_START_YEAR,
    TREND_STREAK_BONUS_PER_YEAR,
)


# ---------------------------------------------------------------------------
# Value object
# ---------------------------------------------------------------------------

@dataclass
class TrendScoreData:
    """All computed trend components for a single topic."""
    topic_id: str
    chapter: str
    trend_score_raw: float
    gap_bonus: float
    streak_score: float
    direction_multiplier: float
    raw_combined: float      # before sigmoid normalization
    p_appears: float         # final [0, 1] probability


# ---------------------------------------------------------------------------
# TrendScoreComputer
# ---------------------------------------------------------------------------

class TrendScoreComputer:
    """
    Stateless pipeline that converts a topic × year question-count matrix into
    per-topic appearance probabilities for the current JEE exam year.

    The year_matrix shape is:
      { "chapter::topic": { 2019: 3, 2020: 2, 2021: 0, ... } }

    Missing year keys are treated as count = 0.

    Usage:
      scorer = TrendScoreComputer(current_year=2026)
      results = scorer.compute_all(year_matrix)
    """

    def __init__(self, current_year: int) -> None:
        self.current_year = current_year
        self._years = list(range(TREND_START_YEAR, current_year))  # years with data

    # -----------------------------------------------------------------------
    # Component 1 — Exponential Decay Trend Score (§2.1)
    # -----------------------------------------------------------------------

    def compute_trend_score_raw(
        self,
        topic_id: str,
        year_matrix: Dict[str, Dict[int, int]],
    ) -> float:
        """
        Σ count(topic, y) × exp(−λ × (current_year − y))  for y in [start, current−1].

        Gives more weight to recent years. A topic with count=3 in 2024 scores
        higher than the same count in 2019.
        """
        counts = year_matrix.get(topic_id, {})
        total = 0.0
        for y in self._years:
            count = counts.get(y, 0)
            decay = math.exp(-TREND_DECAY_LAMBDA * (self.current_year - y))
            total += count * decay
        return total

    # -----------------------------------------------------------------------
    # Component 2 — Gap Bonus (§2.2)
    # -----------------------------------------------------------------------

    def compute_gap_bonus(
        self,
        topic_id: str,
        year_matrix: Dict[str, Dict[int, int]],
    ) -> float:
        """
        Topics that did NOT appear recently but appeared before get a bonus.

        gap_bonus = min(1 + 0.25 × years_since_last, 1.75)

        A topic last seen 3 years ago gets a 1.75× multiplier (the cap).
        A topic that appeared last year gets 1.0 (no bonus).
        """
        counts = year_matrix.get(topic_id, {})
        last_appeared = None
        for y in self._years:
            if counts.get(y, 0) > 0:
                last_appeared = y

        if last_appeared is None:
            # Never appeared — still give a small base bonus to surface it
            return 1.0

        years_since = (self.current_year - 1) - last_appeared
        if years_since < 0:
            years_since = 0
        bonus = 1.0 + TREND_GAP_BONUS_PER_YEAR * years_since
        return min(bonus, TREND_GAP_BONUS_CAP)

    # -----------------------------------------------------------------------
    # Component 3 — Streak Score (§2.3)
    # -----------------------------------------------------------------------

    def compute_streak_score(
        self,
        topic_id: str,
        year_matrix: Dict[str, Dict[int, int]],
    ) -> float:
        """
        Reward topics that have appeared in consecutive recent years.

        streak = length of the longest run of consecutive years ending at current_year−1
        streak_score = 1 + 0.15 × min(streak, 5)

        Topics appearing every year for 5+ years score 1.75× (e.g., integration).
        """
        counts = year_matrix.get(topic_id, {})
        streak = 0
        for y in reversed(self._years):
            if counts.get(y, 0) > 0:
                streak += 1
            else:
                break  # streak broken
        capped = min(streak, TREND_MAX_STREAK_YEARS)
        return 1.0 + TREND_STREAK_BONUS_PER_YEAR * capped

    # -----------------------------------------------------------------------
    # Component 4 — Volume Trend Direction (§2.4)
    # -----------------------------------------------------------------------

    def compute_direction_multiplier(
        self,
        topic_id: str,
        year_matrix: Dict[str, Dict[int, int]],
        window_years: int = 6,
    ) -> float:
        """
        Nudge based on whether question count is increasing or decreasing.

        Uses linear regression over the most recent `window_years` of data.
        slope > 0 → increasing → small upward nudge (max +20%)
        slope < 0 → declining → small downward nudge (max −20%)

        direction_multiplier = 1 + 0.1 × sign(slope) × min(|slope|, 2)
        """
        counts = year_matrix.get(topic_id, {})
        years = list(range(self.current_year - window_years, self.current_year))
        year_counts = [counts.get(y, 0) for y in years]
        slope = self._linear_slope(years, year_counts)
        clamped = max(-TREND_DIRECTION_MAX_SLOPE, min(TREND_DIRECTION_MAX_SLOPE, slope))
        sign = 1 if clamped > 0 else (-1 if clamped < 0 else 0)
        return 1.0 + TREND_DIRECTION_FACTOR * sign * abs(clamped)

    # -----------------------------------------------------------------------
    # Final normalization — §2.5
    # -----------------------------------------------------------------------

    @staticmethod
    def _sigmoid(x: float) -> float:
        """Standard logistic sigmoid: 1 / (1 + exp(−x))."""
        return 1.0 / (1.0 + math.exp(-x))

    @staticmethod
    def _compute_p_appears(
        raw_combined: Dict[str, float],
    ) -> Dict[str, float]:
        """
        Normalize raw_combined scores across all topics and apply sigmoid.

        p_appears(t) = sigmoid(sharpness × (score(t) / max_score − 0.5))

        Topics near the maximum get p ≈ 0.88; topics near zero get p ≈ 0.12.
        The sigmoid's sharpness=3 means a topic at 50% of max gets p ≈ 0.5.
        """
        if not raw_combined:
            return {}
        max_raw = max(raw_combined.values())
        if max_raw == 0.0:
            return {tid: 0.5 for tid in raw_combined}
        result: Dict[str, float] = {}
        for tid, score in raw_combined.items():
            normalized = score / max_raw
            result[tid] = TrendScoreComputer._sigmoid(
                TREND_SIGMOID_SHARPNESS * (normalized - 0.5)
            )
        return result

    # -----------------------------------------------------------------------
    # Linear regression helper
    # -----------------------------------------------------------------------

    @staticmethod
    def _linear_slope(xs: List[int], ys: List[int]) -> float:
        """
        Ordinary-least-squares slope for (x, y) pairs.

        Returns 0.0 if there is no variance in x (degenerate case).
        """
        n = len(xs)
        if n < 2:
            return 0.0
        x_mean = sum(xs) / n
        y_mean = sum(ys) / n
        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
        denominator = sum((x - x_mean) ** 2 for x in xs)
        if denominator == 0.0:
            return 0.0
        return numerator / denominator

    # -----------------------------------------------------------------------
    # Public entrypoint
    # -----------------------------------------------------------------------

    def compute_all(
        self,
        year_matrix: Dict[str, Dict[int, int]],
        topic_chapters: Optional[Dict[str, str]] = None,
    ) -> Dict[str, TrendScoreData]:
        """
        Run the full pipeline for every topic in year_matrix.

        Parameters
        ----------
        year_matrix   : { topic_id: { year: count } }
        topic_chapters: optional mapping topic_id → chapter name for the output doc.

        Returns a dict topic_id → TrendScoreData with all components filled in.
        """
        # Step 1: compute all four raw components
        raw_combined: Dict[str, float] = {}
        components: Dict[str, Tuple[float, float, float, float]] = {}

        for topic_id in year_matrix:
            raw = self.compute_trend_score_raw(topic_id, year_matrix)
            gap = self.compute_gap_bonus(topic_id, year_matrix)
            streak = self.compute_streak_score(topic_id, year_matrix)
            direction = self.compute_direction_multiplier(topic_id, year_matrix)
            combined = raw * gap * streak * direction
            raw_combined[topic_id] = combined
            components[topic_id] = (raw, gap, streak, direction)

        # Step 2: normalize and sigmoid
        p_appears_map = self._compute_p_appears(raw_combined)

        # Step 3: assemble output
        results: Dict[str, TrendScoreData] = {}
        for topic_id, (raw, gap, streak, direction) in components.items():
            chapter = (topic_chapters or {}).get(topic_id, topic_id.split("::")[0])
            results[topic_id] = TrendScoreData(
                topic_id=topic_id,
                chapter=chapter,
                trend_score_raw=round(raw, 4),
                gap_bonus=round(gap, 4),
                streak_score=round(streak, 4),
                direction_multiplier=round(direction, 4),
                raw_combined=round(raw_combined[topic_id], 4),
                p_appears=round(p_appears_map.get(topic_id, 0.5), 4),
            )

        return results

    def high_priority_topics(
        self,
        results: Dict[str, TrendScoreData],
    ) -> List[str]:
        """Return topic_ids where p_appears exceeds the high-priority threshold."""
        return [
            tid
            for tid, data in results.items()
            if data.p_appears >= TREND_HIGH_PRIORITY_THRESHOLD
        ]
