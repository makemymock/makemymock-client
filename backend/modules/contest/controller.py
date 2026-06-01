"""Student-facing contest routes.

Mounted under /api/v1/contests by api/__init__.py.

  GET  /contests                       — Upcoming / live / past lists for the user.
  GET  /contests/{id}                  — Lobby detail (rules, schedule, user state).
  POST /contests/{id}/enter            — Mark lobby entry (opens 5 min before start).
  POST /contests/{id}/start            — Begin contest (idempotent on refresh).
  POST /contests/{id}/submit           — Grade + persist responses.
  GET  /contests/{id}/result           — Per-user result + ranked snapshot.
  GET  /contests/{id}/leaderboard      — Top participants for the contest.
"""

from __future__ import annotations

from fastapi import APIRouter

from core.dependencies import CurrentVerifiedUser, DBDep
from modules.contest.schema import (
    ContestListResponse,
    ContestLobbyResponse,
    ContestResultResponse,
    EnterLobbyResponse,
    LeaderboardResponse,
    StartContestResponse,
    SubmitContestRequest,
)
from modules.contest.service import ContestService

router = APIRouter(prefix="/contests", tags=["Contests"])


@router.get(
    "",
    response_model=ContestListResponse,
    summary="Upcoming, live, and past contests for the current user",
)
async def list_contests(
    user: CurrentVerifiedUser, db: DBDep,
) -> ContestListResponse:
    return await ContestService(db).list_for_user(user["_id"])


@router.get(
    "/{contest_id}",
    response_model=ContestLobbyResponse,
    summary="Contest detail + the user's per-contest state",
)
async def get_contest(
    contest_id: str, user: CurrentVerifiedUser, db: DBDep,
) -> ContestLobbyResponse:
    return await ContestService(db).get_lobby(contest_id, user)


@router.post(
    "/{contest_id}/enter",
    response_model=EnterLobbyResponse,
    summary="Enter the contest lobby (opens 5 minutes before start)",
)
async def enter_lobby(
    contest_id: str, user: CurrentVerifiedUser, db: DBDep,
) -> EnterLobbyResponse:
    return await ContestService(db).enter_lobby(contest_id, user)


@router.post(
    "/{contest_id}/start",
    response_model=StartContestResponse,
    summary="Begin the contest. Returns the question payload + server timer.",
)
async def start_contest(
    contest_id: str, user: CurrentVerifiedUser, db: DBDep,
) -> StartContestResponse:
    return await ContestService(db).start(contest_id, user)


@router.post(
    "/{contest_id}/submit",
    response_model=ContestResultResponse,
    summary="Submit answers, grade, and return the full result + rank",
)
async def submit_contest(
    contest_id: str,
    payload: SubmitContestRequest,
    user: CurrentVerifiedUser,
    db: DBDep,
) -> ContestResultResponse:
    return await ContestService(db).submit(contest_id, user, payload)


@router.get(
    "/{contest_id}/result",
    response_model=ContestResultResponse,
    summary="Fetch the user's saved result for a submitted contest",
)
async def get_result(
    contest_id: str, user: CurrentVerifiedUser, db: DBDep,
) -> ContestResultResponse:
    return await ContestService(db).get_result(contest_id, user)


@router.get(
    "/{contest_id}/leaderboard",
    response_model=LeaderboardResponse,
    summary="Top participants for a contest (ranked by score, then time taken)",
)
async def get_leaderboard(
    contest_id: str, user: CurrentVerifiedUser, db: DBDep,
) -> LeaderboardResponse:
    return await ContestService(db).get_leaderboard(contest_id, user)
