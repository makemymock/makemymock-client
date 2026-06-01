"""FastAPI routes for Problem-of-the-Day.

Mounted under /api/v1/potd by api/__init__.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from core.dependencies import CurrentVerifiedUser, DBDep
from modules.potd.constants import DEFAULT_HISTORY_DAYS, MAX_HISTORY_DAYS
from modules.potd.schema import (
    AttemptRequest,
    AttemptResponse,
    HistoryResponse,
    PastDateResponse,
    StreakResponse,
    TodayResponse,
    ViewSolutionResponse,
)
from modules.potd.service import PotdService

router = APIRouter(prefix="/potd", tags=["POTD"])


@router.get(
    "/today",
    response_model=TodayResponse,
    summary="Fetch (or materialise) today's POTD for the current user",
)
async def get_today(
    user: CurrentVerifiedUser, db: DBDep,
) -> TodayResponse:
    return await PotdService(db).get_today(user["_id"])


@router.post(
    "/today/attempt",
    response_model=AttemptResponse,
    summary="Grade an attempt at today's POTD",
)
async def submit_attempt(
    payload: AttemptRequest, user: CurrentVerifiedUser, db: DBDep,
) -> AttemptResponse:
    return await PotdService(db).submit_attempt(user["_id"], payload)


@router.post(
    "/today/view-solution",
    response_model=ViewSolutionResponse,
    summary="Reveal today's solution (breaks streak if not already solved)",
)
async def view_solution(
    user: CurrentVerifiedUser, db: DBDep,
) -> ViewSolutionResponse:
    return await PotdService(db).view_solution(user["_id"])


@router.get(
    "/streak",
    response_model=StreakResponse,
    summary="Current + longest POTD streak for the user",
)
async def get_streak(
    user: CurrentVerifiedUser, db: DBDep,
) -> StreakResponse:
    return await PotdService(db).get_streak(user["_id"])


@router.get(
    "/history",
    response_model=HistoryResponse,
    summary="Per-day POTD engagement over the requested window",
)
async def get_history(
    user: CurrentVerifiedUser,
    db: DBDep,
    days: int = Query(DEFAULT_HISTORY_DAYS, ge=1, le=MAX_HISTORY_DAYS),
) -> HistoryResponse:
    return await PotdService(db).get_history(user["_id"], days=days)


@router.get(
    "/{date_ist}",
    response_model=PastDateResponse,
    summary="Past-date POTD detail (question + solution) for the calendar click",
)
async def get_past_date(
    date_ist: str, user: CurrentVerifiedUser, db: DBDep,
) -> PastDateResponse:
    return await PotdService(db).get_past_date(user["_id"], date_ist)
