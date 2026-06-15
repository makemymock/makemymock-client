"""Lightweight in-process counters for the batch pass.

The mining job is a one-shot offline run, so plain counters logged at
end-of-run are enough — no Prometheus, no Mongo doc. The HTTP read API never
touches these; they exist purely for the `jobs/` summaries.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class _Metrics:
    classified: int = 0
    new_patterns: int = 0
    joined_new_under_lock: int = 0
    llm_calls: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    llm_errors: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    latency_ms_sum: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _lock: Lock = field(default_factory=Lock)

    def record_llm_call(self, *, agent: str, ok: bool, latency_ms: int) -> None:
        with self._lock:
            self.llm_calls[agent] += 1
            if not ok:
                self.llm_errors[agent] += 1
            self.latency_ms_sum[agent] += latency_ms

    def record_outcome(self, outcome: str) -> None:
        """Record one classified question.

        outcome ∈ {"matched", "created", "joined_existing", "joined_lock"}:
          * created      → a brand-new pattern was minted
          * joined_lock  → joined an existing pattern via the in-lock recheck
          * matched / joined_existing → joined via stage-1/2 or slug-dup fallback
        """
        with self._lock:
            if outcome == "created":
                self.new_patterns += 1
            elif outcome == "joined_lock":
                self.joined_new_under_lock += 1
            self.classified += 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "classified": self.classified,
                "new_patterns": self.new_patterns,
                "joined_new_under_lock": self.joined_new_under_lock,
                "llm_calls": dict(self.llm_calls),
                "llm_errors": dict(self.llm_errors),
                "latency_ms_avg": {
                    a: (self.latency_ms_sum[a] // max(self.llm_calls[a], 1))
                    for a in self.llm_calls
                },
            }


metrics = _Metrics()
