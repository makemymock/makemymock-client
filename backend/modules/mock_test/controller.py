"""FastAPI routes for the mock-test feature.

Mounted under /api/v1/mock-test by api/__init__.py.
"""

from typing import Optional

from fastapi import APIRouter, Query, status

from core.dependencies import CurrentVerifiedUser, DBDep
from modules.mock_test.schema import (
    ActivityHeatmapResponse,
    AnalyticsChaptersResponse,
    AnalyticsOverviewResponse,
    AnalyticsTopicsResponse,
    BrowseAttemptRequest,
    BrowseAttemptResponse,
    BrowseListResponse,
    BrowseQuestionDetail,
    BrowseSolutionResponse,
    NotebookCountResponse,
    NotebookToggleResponse,
    CatalogResponse,
    ChapterDetailResponse,
    ConfidenceResponse,
    CreateMockTestRequest,
    CreateMockTestResponse,
    HistoryResponse,
    SessionResponse,
    SubmitMockTestRequest,
    SubmitMockTestResponse,
    TopicDetailResponse,
)
from modules.mock_test.service import MockTestService

router = APIRouter(prefix="/mock-test", tags=["Mock Test"])


@router.get(
    "/catalog",
    response_model=CatalogResponse,
    summary="List available subjects → chapters → topics for test selection",
)
async def get_catalog(
    _user: CurrentVerifiedUser, db: DBDep,
) -> CatalogResponse:
    return await MockTestService(db).get_catalog()


@router.get(
    "/browse",
    response_model=BrowseListResponse,
    summary="Paginated, filterable catalog of all questions with per-user status",
)
async def browse_questions(
    user: CurrentVerifiedUser,
    db: DBDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    subject: Optional[str] = None,
    chapter: Optional[str] = None,
    topic: Optional[str] = None,
    difficulty: Optional[str] = None,
    question_type: Optional[str] = None,
    attempted: Optional[bool] = None,
    marked: Optional[bool] = None,
    search: Optional[str] = None,
) -> BrowseListResponse:
    return await MockTestService(db).browse_questions(
        user["_id"],
        subject=subject, chapter=chapter, topic=topic,
        difficulty=difficulty, question_type=question_type,
        attempted=attempted, marked=marked, search=search,
        page=page, page_size=page_size,
    )


@router.get(
    "/browse/{question_id}",
    response_model=BrowseQuestionDetail,
    summary="Full question detail for the Browse problem page (answer gated)",
)
async def browse_question_detail(
    question_id: str,
    user: CurrentVerifiedUser,
    db: DBDep,
) -> BrowseQuestionDetail:
    return await MockTestService(db).get_browse_detail(user["_id"], question_id)


@router.post(
    "/browse/{question_id}/attempt",
    response_model=BrowseAttemptResponse,
    summary="Grade a practice attempt (feeds recommender unless solution was viewed)",
)
async def browse_attempt(
    question_id: str,
    payload: BrowseAttemptRequest,
    user: CurrentVerifiedUser,
    db: DBDep,
) -> BrowseAttemptResponse:
    return await MockTestService(db).record_practice_attempt(
        user["_id"], question_id, payload,
    )


@router.post(
    "/browse/{question_id}/view-solution",
    response_model=BrowseSolutionResponse,
    summary="Reveal the worked solution + answer; marks the question as viewed",
)
async def browse_view_solution(
    question_id: str,
    user: CurrentVerifiedUser,
    db: DBDep,
) -> BrowseSolutionResponse:
    return await MockTestService(db).view_solution(user["_id"], question_id)


@router.get(
    "/notebook/count",
    response_model=NotebookCountResponse,
    summary="Number of questions in the current user's notebook",
)
async def notebook_count(
    user: CurrentVerifiedUser, db: DBDep,
) -> NotebookCountResponse:
    return await MockTestService(db).get_notebook_count(user["_id"])


@router.post(
    "/notebook/{question_id}",
    response_model=NotebookToggleResponse,
    summary="Add a question to the notebook (idempotent — can't be added twice)",
)
async def notebook_add(
    question_id: str,
    user: CurrentVerifiedUser,
    db: DBDep,
) -> NotebookToggleResponse:
    return await MockTestService(db).add_to_notebook(user["_id"], question_id)


@router.delete(
    "/notebook/{question_id}",
    response_model=NotebookToggleResponse,
    summary="Remove a question from the notebook",
)
async def notebook_remove(
    question_id: str,
    user: CurrentVerifiedUser,
    db: DBDep,
) -> NotebookToggleResponse:
    return await MockTestService(db).remove_from_notebook(user["_id"], question_id)


@router.post(
    "/create",
    response_model=CreateMockTestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a personalized mock test for the current user",
)
async def create_test(
    payload: CreateMockTestRequest,
    user: CurrentVerifiedUser,
    db: DBDep,
) -> CreateMockTestResponse:
    return await MockTestService(db).create_test(user["_id"], payload)


@router.get(
    "/session/{session_id}",
    response_model=SessionResponse,
    summary="Fetch a mock-test session (used to resume after a refresh)",
)
async def get_session(
    session_id: int,
    user: CurrentVerifiedUser,
    db: DBDep,
) -> SessionResponse:
    return await MockTestService(db).get_session_for_user(user["_id"], session_id)


@router.post(
    "/session/{session_id}/submit",
    response_model=SubmitMockTestResponse,
    summary="Submit answers, run grading, persist attempts, return results",
)
async def submit_test(
    session_id: int,
    payload: SubmitMockTestRequest,
    user: CurrentVerifiedUser,
    db: DBDep,
) -> SubmitMockTestResponse:
    return await MockTestService(db).submit_test(user["_id"], session_id, payload)


@router.get(
    "/session/{session_id}/result",
    response_model=SubmitMockTestResponse,
    summary="Fetch results for a completed mock test",
)
async def get_result(
    session_id: int,
    user: CurrentVerifiedUser,
    db: DBDep,
) -> SubmitMockTestResponse:
    return await MockTestService(db).get_results(user["_id"], session_id)


@router.get(
    "/history",
    response_model=HistoryResponse,
    summary="List the current user's recent mock tests",
)
async def history(
    user: CurrentVerifiedUser, db: DBDep,
) -> HistoryResponse:
    return await MockTestService(db).get_history(user["_id"])


@router.get(
    "/analytics/overview",
    response_model=AnalyticsOverviewResponse,
    summary="Aggregated analytics across all of the user's mock tests",
)
async def analytics_overview(
    user: CurrentVerifiedUser, db: DBDep,
) -> AnalyticsOverviewResponse:
    return await MockTestService(db).get_overview(user["_id"])


@router.get(
    "/analytics/topics",
    response_model=AnalyticsTopicsResponse,
    summary="Per-topic priority and accuracy for the current user",
)
async def analytics_topics(
    user: CurrentVerifiedUser, db: DBDep,
) -> AnalyticsTopicsResponse:
    return await MockTestService(db).get_topic_analytics(user["_id"])


@router.get(
    "/analytics/chapters",
    response_model=AnalyticsChaptersResponse,
    summary="Per-chapter rollup analytics for the current user",
)
async def analytics_chapters(
    user: CurrentVerifiedUser, db: DBDep,
) -> AnalyticsChaptersResponse:
    return await MockTestService(db).get_chapter_analytics(user["_id"])


@router.get(
    "/analytics/chapter/{chapter_id}",
    response_model=ChapterDetailResponse,
    summary="Drill-down analytics for a single chapter",
)
async def analytics_chapter_detail(
    chapter_id: int,
    user: CurrentVerifiedUser,
    db: DBDep,
) -> ChapterDetailResponse:
    return await MockTestService(db).get_chapter_detail(user["_id"], chapter_id)


@router.get(
    "/analytics/topic/{topic_id}",
    response_model=TopicDetailResponse,
    summary="Drill-down analytics for a single topic",
)
async def analytics_topic_detail(
    topic_id: int,
    user: CurrentVerifiedUser,
    db: DBDep,
) -> TopicDetailResponse:
    return await MockTestService(db).get_topic_detail(user["_id"], topic_id)


@router.get(
    "/analytics/activity-heatmap",
    response_model=ActivityHeatmapResponse,
    summary=(
        "Dense daily-attempt counts over the last 6 months — used by the "
        "dashboard / analytics heatmap to show practice intensity"
    ),
)
async def analytics_activity_heatmap(
    user: CurrentVerifiedUser, db: DBDep,
) -> ActivityHeatmapResponse:
    return await MockTestService(db).get_activity_heatmap(user["_id"])


@router.get(
    "/analytics/confidence",
    response_model=ConfidenceResponse,
    summary=(
        "Gamified Confidence Score (0–100) + trophy tier. Weighted blend "
        "of volume, accuracy, consistency, 1v1 battles, and POTD streak."
    ),
)
async def analytics_confidence(
    user: CurrentVerifiedUser, db: DBDep,
) -> ConfidenceResponse:
    return await MockTestService(db).get_confidence(user["_id"])
