from __future__ import annotations

import math
from dataclasses import dataclass

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


@dataclass
class TrendScoreData:
    topic_id: str
    chapter: str
    trend_score_raw: float
    gap_bonus: float
    streak_score: float
    direction_multiplier: float
    raw_combined: float
    p_appears: float


class TrendScoreComputer:
    def __init__(self, current_year: int) -> None:
        self.current_year = current_year
        self._years = list(range(TREND_START_YEAR, current_year))

    def compute_trend_score_raw(self, topic_id: str, year_matrix: dict) -> float:
        counts = year_matrix.get(topic_id, {})
        return sum(
            counts.get(y, 0) * math.exp(-TREND_DECAY_LAMBDA * (self.current_year - y))
            for y in self._years
        )

    def compute_gap_bonus(self, topic_id: str, year_matrix: dict) -> float:
        counts = year_matrix.get(topic_id, {})
        last_appeared = next((y for y in reversed(self._years) if counts.get(y, 0) > 0), None)
        if last_appeared is None:
            return 1.0
        years_since = max(0, (self.current_year - 1) - last_appeared)
        return min(1.0 + TREND_GAP_BONUS_PER_YEAR * years_since, TREND_GAP_BONUS_CAP)

    def compute_streak_score(self, topic_id: str, year_matrix: dict) -> float:
        counts = year_matrix.get(topic_id, {})
        streak = 0
        for y in reversed(self._years):
            if counts.get(y, 0) > 0:
                streak += 1
            else:
                break
        return 1.0 + TREND_STREAK_BONUS_PER_YEAR * min(streak, TREND_MAX_STREAK_YEARS)

    def compute_direction_multiplier(self, topic_id: str, year_matrix: dict, window_years: int = 6) -> float:
        counts = year_matrix.get(topic_id, {})
        years = list(range(self.current_year - window_years, self.current_year))
        slope = self._linear_slope(years, [counts.get(y, 0) for y in years])
        clamped = max(-TREND_DIRECTION_MAX_SLOPE, min(TREND_DIRECTION_MAX_SLOPE, slope))
        sign = 1 if clamped > 0 else (-1 if clamped < 0 else 0)
        return 1.0 + TREND_DIRECTION_FACTOR * sign * abs(clamped)

    @staticmethod
    def _sigmoid(x: float) -> float:
        return 1.0 / (1.0 + math.exp(-x))

    @staticmethod
    def _compute_p_appears(raw_combined: dict[str, float]) -> dict[str, float]:
        if not raw_combined: return {}
        max_raw = max(raw_combined.values())
        if max_raw == 0.0:
            return {tid: 0.5 for tid in raw_combined}
        return {
            tid: TrendScoreComputer._sigmoid(TREND_SIGMOID_SHARPNESS * (score / max_raw - 0.5))
            for tid, score in raw_combined.items()
        }

    @staticmethod
    def _linear_slope(xs: list, ys: list) -> float:
        n = len(xs)
        if n < 2: return 0.0
        x_mean = sum(xs) / n
        y_mean = sum(ys) / n
        num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
        den = sum((x - x_mean) ** 2 for x in xs)
        return 0.0 if den == 0.0 else num / den

    def compute_all(self, year_matrix: dict, topic_chapters: dict | None = None) -> dict[str, TrendScoreData]:
        raw_combined = {}
        components = {}
        for topic_id in year_matrix:
            raw      = self.compute_trend_score_raw(topic_id, year_matrix)
            gap      = self.compute_gap_bonus(topic_id, year_matrix)
            streak   = self.compute_streak_score(topic_id, year_matrix)
            direction = self.compute_direction_multiplier(topic_id, year_matrix)
            raw_combined[topic_id] = raw * gap * streak * direction
            components[topic_id] = (raw, gap, streak, direction)

        p_appears_map = self._compute_p_appears(raw_combined)

        return {
            topic_id: TrendScoreData(
                topic_id=topic_id,
                chapter=(topic_chapters or {}).get(topic_id, topic_id.split("::")[0]),
                trend_score_raw=round(raw, 4),
                gap_bonus=round(gap, 4),
                streak_score=round(streak, 4),
                direction_multiplier=round(direction, 4),
                raw_combined=round(raw_combined[topic_id], 4),
                p_appears=round(p_appears_map.get(topic_id, 0.5), 4),
            )
            for topic_id, (raw, gap, streak, direction) in components.items()
        }

    def high_priority_topics(self, results: dict[str, TrendScoreData]) -> list[str]:
        return [tid for tid, data in results.items() if data.p_appears >= TREND_HIGH_PRIORITY_THRESHOLD]
