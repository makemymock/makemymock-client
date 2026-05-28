"""
FastAPI routes for the JEE Recommender module.

Mounted under /api/v1/recommender by api/__init__.py.

student_id is ALWAYS derived from the bearer token (user["_id"]) — it is
never accepted as a client-supplied parameter. This matches the security
pattern used by every other module in this codebase.

The controller never touches the database directly. It receives a
RecommenderService instance via FastAPI dependency injection (RecommenderDep)
and delegates all work to the service layer.

Route map:
  POST /initialize            — create 156 topic states + personality for current user
  POST /session/start         — Session Planner Agent → SessionPlan
  POST /session/next-question — hot loop → next question_id
  POST /session/submit-answer — process answer, update math state
  POST /session/end           — finalize session, trigger async diagnosis
  GET  /personality           — fetch personality doc for current user
  GET  /topic-states          — all 156 topic states with unlock status
  GET  /sessions              — recent session summaries
  GET  /trends                — all topic trend scores
  POST /admin/run-trend-update — trigger Trend Intelligence Agent (admin)
"""

from typing import Annotated, TypeAlias

from fastapi import APIRouter, Depends, status

from core.dependencies import CurrentVerifiedUser, DBDep
from modules.recommender.schema import (
    AllTopicStatesResponse,
    AllTrendScoresResponse,
    EndSessionRequest,
    EndSessionResponse,
    InitializeStudentResponse,
    NextQuestionRequest,
    NextQuestionResponse,
    QuestionDetailResponse,
    SessionHistoryResponse,
    SessionPlanResponse,
    StudentPersonalityResponse,
    StudentStatsResponse,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
    TrendUpdateResponse,
)
from modules.recommender.service import RecommenderService

router = APIRouter(prefix="/recommender", tags=["Recommender"])


# ---------------------------------------------------------------------------
# Service dependency — controllers never reference DBDep directly
# ---------------------------------------------------------------------------

def _get_service(db: DBDep) -> RecommenderService:
    """Inject a RecommenderService bound to the request-scoped Motor database."""
    return RecommenderService(db)


RecommenderDep = Annotated[RecommenderService, Depends(_get_service)]


# ---------------------------------------------------------------------------
# Student initialization
# ---------------------------------------------------------------------------

@router.post(
    "/initialize",
    response_model=InitializeStudentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Initialize 156 topic states and personality doc for the current user (run once)",
)
async def initialize_student(
    user: CurrentVerifiedUser,
    service: RecommenderDep,
) -> InitializeStudentResponse:
    return await service.initialize_student(str(user["_id"]))


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

@router.post(
    "/session/start",
    response_model=SessionPlanResponse,
    summary="Run Session Planner Agent and return the session plan + initial state",
)
async def start_session(
    user: CurrentVerifiedUser,
    service: RecommenderDep,
) -> SessionPlanResponse:
    return await service.start_session(str(user["_id"]))


@router.post(
    "/session/next-question",
    response_model=NextQuestionResponse,
    summary=(
        "Hot loop: Confidence Regulator → Spaced Repetition → "
        "Thompson Sampling → IRT → Question Selector Agent"
    ),
)
async def get_next_question(
    payload: NextQuestionRequest,
    user: CurrentVerifiedUser,
    service: RecommenderDep,
) -> NextQuestionResponse:
    return await service.get_next_question(
        student_id=str(user["_id"]),
        session_id=payload.session_id,
        focus_topics=payload.focus_topics,
        start_difficulty_offset=payload.start_difficulty_offset,
        review_injection_rate=payload.review_injection_rate,
        state=payload.state,
    )


@router.post(
    "/session/submit-answer",
    response_model=SubmitAnswerResponse,
    summary=(
        "Process an answer: update Beta/IRT/SM-2 state, "
        "check prereq unlock, trigger diagnosis on frustration"
    ),
)
async def submit_answer(
    payload: SubmitAnswerRequest,
    user: CurrentVerifiedUser,
    service: RecommenderDep,
) -> SubmitAnswerResponse:
    return await service.process_answer(
        student_id=str(user["_id"]),
        session_id=payload.session_id,
        question_id=payload.question_id,
        topic_id=payload.topic_id,
        chapter=payload.chapter,
        correct=payload.correct,
        time_ms=payload.time_ms,
        difficulty=payload.difficulty,
        question_type=payload.question_type,
        state=payload.state,
    )


@router.post(
    "/session/end",
    response_model=EndSessionResponse,
    summary="End session: store summary, trigger async Diagnosis Agent",
)
async def end_session(
    payload: EndSessionRequest,
    user: CurrentVerifiedUser,
    service: RecommenderDep,
) -> EndSessionResponse:
    return await service.end_session(
        student_id=str(user["_id"]),
        session_id=payload.session_id,
        state=payload.state,
        started_at=payload.started_at,
    )


# ---------------------------------------------------------------------------
# Student read endpoints — current user only
# ---------------------------------------------------------------------------

@router.get(
    "/personality",
    response_model=StudentPersonalityResponse,
    summary="Fetch the current user's compressed personality document (updated after each session)",
)
async def get_personality(
    user: CurrentVerifiedUser,
    service: RecommenderDep,
) -> StudentPersonalityResponse:
    return await service.get_personality(str(user["_id"]))


@router.get(
    "/topic-states",
    response_model=AllTopicStatesResponse,
    summary="All 156 topic states with mastery, IRT theta, SM-2 schedule, and unlock status",
)
async def get_topic_states(
    user: CurrentVerifiedUser,
    service: RecommenderDep,
) -> AllTopicStatesResponse:
    return await service.get_all_topic_states(str(user["_id"]))


@router.get(
    "/sessions",
    response_model=SessionHistoryResponse,
    summary="Recent session summaries for the current user",
)
async def get_session_history(
    user: CurrentVerifiedUser,
    service: RecommenderDep,
) -> SessionHistoryResponse:
    return await service.get_session_history(str(user["_id"]))


# ---------------------------------------------------------------------------
# Trend scores — read-only, visible to all authenticated users
# ---------------------------------------------------------------------------

@router.get(
    "/trends",
    response_model=AllTrendScoresResponse,
    summary="All topic trend scores (p_appears, gap bonus, streak, direction) — recomputed weekly",
)
async def get_trend_scores(
    _user: CurrentVerifiedUser,
    service: RecommenderDep,
) -> AllTrendScoresResponse:
    return await service.get_trend_scores()


# ---------------------------------------------------------------------------
# Question detail & student stats — frontend helpers
# ---------------------------------------------------------------------------

@router.get(
    "/question/{question_id}",
    response_model=QuestionDetailResponse,
    summary="Fetch PYQ question content by question_id for in-session display",
)
async def get_question_detail(
    question_id: str,
    user: CurrentVerifiedUser,
    service: RecommenderDep,
) -> QuestionDetailResponse:
    return await service.get_question_detail(question_id)


@router.get(
    "/stats",
    response_model=StudentStatsResponse,
    summary="Aggregate question attempt stats for the current student",
)
async def get_student_stats(
    user: CurrentVerifiedUser,
    service: RecommenderDep,
) -> StudentStatsResponse:
    return await service.get_student_stats(str(user["_id"]))


# ---------------------------------------------------------------------------
# Admin — weekly trend update trigger
# ---------------------------------------------------------------------------

@router.post(
    "/admin/run-trend-update",
    response_model=TrendUpdateResponse,
    summary="Trigger Trend Intelligence Agent to recompute all p_appears scores (admin/cron)",
)
async def run_trend_update(
    _user: CurrentVerifiedUser,
    service: RecommenderDep,
) -> TrendUpdateResponse:
    return await service.run_trend_update()
