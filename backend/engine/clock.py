"""Time injection.

The decay logic in Layer 2 depends on `datetime.utcnow() - attempted_at`, so
every code path that needs "now" goes through a Clock. Tests inject FakeClock
to make decay deterministic; production injects SystemClock.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.utcnow()
