"""Pattern-learning HTTP surface (the Duolingo path).

Browse subjects → chapters → the chapter's pattern roadmap → a pattern's
question roadmap → solve a question. All routes are auth-gated; the unlock state
is computed per student from their mock accuracy + prior submissions.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from core.dependencies import CurrentVerifiedUser, DBDep
from modules.pattern_learning.schema import (
    ChapterList,
    PatternRoadmap,
    QuestionContent,
    QuestionRoadmap,
    SubjectList,
    SubmitAnswerRequest,
    SubmitResult,
)
from modules.pattern_learning.service import PatternLearningService

router = APIRouter(prefix="/pattern-learning", tags=["Pattern Learning"])

_LOCKED_DETAIL = "This is locked — finish the earlier questions first."


@router.get(
    "/subjects",
    response_model=SubjectList,
    summary="Subjects that have a mined pattern path",
)
async def list_subjects(db: DBDep, current_user: CurrentVerifiedUser) -> SubjectList:
    data = await PatternLearningService(db).list_subjects()
    return SubjectList(**data)


@router.get(
    "/subjects/{subject}/chapters",
    response_model=ChapterList,
    summary="Chapters in a subject, with each chapter's unlock state",
)
async def list_chapters(
    subject: str, db: DBDep, current_user: CurrentVerifiedUser,
) -> ChapterList:
    data = await PatternLearningService(db).list_chapters(subject, current_user["_id"])
    return ChapterList(**data)


@router.get(
    "/chapters/{chapter}/patterns",
    response_model=PatternRoadmap,
    summary="The chapter's pattern roadmap (locked / unlocked / completed)",
)
async def chapter_patterns(
    chapter: str, db: DBDep, current_user: CurrentVerifiedUser,
) -> PatternRoadmap:
    data = await PatternLearningService(db).pattern_roadmap(chapter, current_user["_id"])
    return PatternRoadmap(**data)


@router.get(
    "/patterns/{pattern_id}/questions",
    response_model=QuestionRoadmap,
    summary="A pattern's question roadmap (locked / unlocked / solved)",
)
async def pattern_questions(
    pattern_id: str, db: DBDep, current_user: CurrentVerifiedUser,
) -> QuestionRoadmap:
    data = await PatternLearningService(db).question_roadmap(pattern_id, current_user["_id"])
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pattern not found."
        )
    return QuestionRoadmap(**data)


@router.get(
    "/questions/{question_id}",
    response_model=QuestionContent,
    summary="A question's content for solving (answer revealed once submitted)",
)
async def get_question(
    question_id: str, db: DBDep, current_user: CurrentVerifiedUser,
) -> QuestionContent:
    data, err = await PatternLearningService(db).get_question_content(
        question_id, current_user["_id"]
    )
    if err == "locked":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_LOCKED_DETAIL)
    if err or data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Question not found."
        )
    return QuestionContent(**data)


@router.post(
    "/questions/{question_id}/submit",
    response_model=SubmitResult,
    summary="Submit an answer — grades, reveals the solution, unlocks the next",
)
async def submit_answer(
    question_id: str,
    payload: SubmitAnswerRequest,
    db: DBDep,
    current_user: CurrentVerifiedUser,
) -> SubmitResult:
    data, err = await PatternLearningService(db).submit_answer(
        question_id, current_user["_id"], payload.answer
    )
    if err == "locked":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_LOCKED_DETAIL)
    if err or data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Question not found."
        )
    return SubmitResult(**data)
