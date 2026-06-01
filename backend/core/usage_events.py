"""Append-only log of cost-bearing / admin-interesting events.

Schema (each doc):
    {
        "ts":          datetime (UTC, indexed),
        "source":      str — "solverx" | "mock_test" | "battle" | "potd" | ...
        "user_id":     ObjectId | None (anonymous = None),
        "model":       str — Vertex AI model id for solverx events; "" otherwise
        "input_tokens":  int (0 when unknown)
        "output_tokens": int (0 when unknown)
        "total_tokens":  int (sum, denormalised for cheap aggregation)
        "duration_ms": int — wall-clock time for the action
        "status":      "ok" | "error"
        "error":       str | None — short error message when status="error"
        "extra":       dict — free-form per-source metadata (e.g. mode, complexity)
    }

Writes are fire-and-forget — the calling path NEVER awaits write success
because dropping a metric write must not break a user-facing call. The
helper catches and logs any Mongo error itself.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId

logger = logging.getLogger(__name__)


# Set by callers before initiating Vertex AI (or other) calls. The llm
# wrapper reads this and records a usage event after the call completes.
# ContextVar is async-task-safe — nested tasks inherit the value, so the
# SolverX pipeline can spawn parallel diagram agents without each having
# to re-set the context.
_usage_context: ContextVar[Optional[dict]] = ContextVar(
    "usage_context", default=None,
)


def get_usage_context() -> Optional[dict]:
    return _usage_context.get()


@asynccontextmanager
async def usage_context(db, *, user_id, source: str, extra: Optional[dict] = None):
    """Wrap a block that performs cost-bearing work so any inner LLM call
    can find the user / db / source via `get_usage_context()`.

    Example:
        async with usage_context(self.db, user_id=user_id, source="solverx",
                                 extra={"mode": "solve"}):
            await chat_json(...)
            await chat_stream(...)  # each records its own event
    """
    token = _usage_context.set({
        "db": db,
        "user_id": user_id,
        "source": source,
        "extra": extra or {},
    })
    try:
        yield
    finally:
        _usage_context.reset(token)


def _coerce_user_id(user_id: Any) -> Optional[ObjectId]:
    if user_id is None:
        return None
    if isinstance(user_id, ObjectId):
        return user_id
    if isinstance(user_id, str):
        try:
            return ObjectId(user_id)
        except Exception:  # noqa: BLE001
            return None
    return None


async def record_event(
    db,
    *,
    source: str,
    user_id: Any = None,
    model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    duration_ms: int = 0,
    status: str = "ok",
    error: Optional[str] = None,
    extra: Optional[dict] = None,
) -> None:
    """Best-effort write of one usage event. Never raises on failure —
    metric drops are preferable to user-facing 500s."""
    try:
        doc = {
            "ts": datetime.now(timezone.utc),
            "source": source,
            "user_id": _coerce_user_id(user_id),
            "model": model or "",
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "total_tokens": int((input_tokens or 0) + (output_tokens or 0)),
            "duration_ms": int(duration_ms or 0),
            "status": status,
            "error": error,
            "extra": extra or {},
        }
        await db["usage_events"].insert_one(doc)
    except Exception as exc:  # noqa: BLE001 — metrics path can't break the caller
        logger.debug("usage_events write dropped: %s", exc)
