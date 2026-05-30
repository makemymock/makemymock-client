import asyncio
import json
from typing import Annotated, TypeAlias

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from core.dependencies import CurrentVerifiedUser, PyQDBDep
from modules.recommender.schema import (
    AllTopicStatesResponse,
    AllTrendScoresResponse,
    AttemptedQuestionsResponse,
    CatalogSubjectsResponse,
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


def _get_service(db: PyQDBDep) -> RecommenderService:
    return RecommenderService(db)


RecommenderDep = Annotated[RecommenderService, Depends(_get_service)]


@router.post("/initialize", response_model=InitializeStudentResponse, status_code=status.HTTP_201_CREATED)
async def initialize_student(user: CurrentVerifiedUser, service: RecommenderDep) -> InitializeStudentResponse:
    return await service.initialize_student(str(user["_id"]))


@router.post("/session/start", response_model=SessionPlanResponse)
async def start_session(user: CurrentVerifiedUser, service: RecommenderDep) -> SessionPlanResponse:
    return await service.start_session(str(user["_id"]))


@router.get("/session/start-stream")
async def start_session_stream(user: CurrentVerifiedUser, service: RecommenderDep) -> StreamingResponse:
    """SSE endpoint: streams agent tool-call events while planning the session.

    Event types (newline-delimited JSON after 'data: '):
      connected  — handshake, no payload
      step       — {type, tool, label, index}  one per tool call as it completes
      confidence — {type, text}  the coach's personalised session note
      plan       — {type, ...SessionPlanResponse fields}  final plan, always last
      error      — {type, message}  on any failure
      done       — sentinel, stream ends
    """
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def _agent_task() -> None:
        try:
            await service.start_session_stream(str(user["_id"]), queue)
        except Exception as exc:
            await queue.put({"type": "error", "message": str(exc)})
        finally:
            await queue.put(None)   # sentinel — close the stream

    asyncio.create_task(_agent_task())

    async def _sse_generator():
        yield 'data: {"type":"connected"}\n\n'
        while True:
            event = await queue.get()
            if event is None:
                yield 'data: {"type":"done"}\n\n'
                break
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(
        _sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",   # disable nginx buffering
        },
    )


@router.post("/session/next-question", response_model=NextQuestionResponse)
async def get_next_question(payload: NextQuestionRequest, user: CurrentVerifiedUser, service: RecommenderDep) -> NextQuestionResponse:
    return await service.get_next_question(
        student_id=str(user["_id"]),
        focus_topics=payload.focus_topics,
        start_difficulty_offset=payload.start_difficulty_offset,
        review_injection_rate=payload.review_injection_rate,
        state=payload.state,
    )


@router.post("/session/submit-answer", response_model=SubmitAnswerResponse)
async def submit_answer(payload: SubmitAnswerRequest, user: CurrentVerifiedUser, service: RecommenderDep) -> SubmitAnswerResponse:
    return await service.process_answer(
        student_id=str(user["_id"]),
        session_id=payload.session_id,
        question_id=payload.question_id,
        topic_id=payload.topic_id,
        correct=payload.correct,
        time_ms=payload.time_ms,
        difficulty=payload.difficulty,
        question_type=payload.question_type,
        state=payload.state,
    )


@router.post("/session/end", response_model=EndSessionResponse)
async def end_session(payload: EndSessionRequest, user: CurrentVerifiedUser, service: RecommenderDep) -> EndSessionResponse:
    return await service.end_session(
        student_id=str(user["_id"]),
        session_id=payload.session_id,
        state=payload.state,
        started_at=payload.started_at,
    )


@router.get("/personality", response_model=StudentPersonalityResponse)
async def get_personality(user: CurrentVerifiedUser, service: RecommenderDep) -> StudentPersonalityResponse:
    return await service.get_personality(str(user["_id"]))


@router.get("/topic-states", response_model=AllTopicStatesResponse)
async def get_topic_states(user: CurrentVerifiedUser, service: RecommenderDep) -> AllTopicStatesResponse:
    return await service.get_all_topic_states(str(user["_id"]))


@router.get("/sessions", response_model=SessionHistoryResponse)
async def get_session_history(user: CurrentVerifiedUser, service: RecommenderDep) -> SessionHistoryResponse:
    return await service.get_session_history(str(user["_id"]))


@router.get("/trends", response_model=AllTrendScoresResponse)
async def get_trend_scores(_user: CurrentVerifiedUser, service: RecommenderDep) -> AllTrendScoresResponse:
    return await service.get_trend_scores()


@router.get("/question/{question_id}", response_model=QuestionDetailResponse)
async def get_question_detail(question_id: str, user: CurrentVerifiedUser, service: RecommenderDep) -> QuestionDetailResponse:
    return await service.get_question_detail(question_id)


@router.get("/stats", response_model=StudentStatsResponse)
async def get_student_stats(user: CurrentVerifiedUser, service: RecommenderDep) -> StudentStatsResponse:
    return await service.get_student_stats(str(user["_id"]))


@router.post("/admin/run-trend-update", response_model=TrendUpdateResponse)
async def run_trend_update(_user: CurrentVerifiedUser, service: RecommenderDep) -> TrendUpdateResponse:
    return await service.run_trend_update()


@router.get("/attempted-questions", response_model=AttemptedQuestionsResponse)
async def get_attempted_questions(
    correct: bool,
    user: CurrentVerifiedUser,
    service: RecommenderDep,
    limit: int = 20,
) -> AttemptedQuestionsResponse:
    return await service.get_attempted_questions(str(user["_id"]), correct=correct, limit=min(limit, 50))


@router.get("/catalog-subjects", response_model=CatalogSubjectsResponse)
async def get_catalog_subjects(_user: CurrentVerifiedUser, service: RecommenderDep) -> CatalogSubjectsResponse:
    return await service.get_catalog_subjects()
