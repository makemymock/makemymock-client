"""SolverX HTTP surface.

Two streaming endpoints (Solve, Theory) return Server-Sent Events. The
non-streaming list + detail endpoints power the chat history sidebar.
"""

from __future__ import annotations

from bson import ObjectId
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from core.dependencies import CurrentVerifiedUser, DBDep
from modules.solverx.schema import (
    ConversationDetail,
    ConversationList,
    SolveRequest,
    TheoryRequest,
)
from modules.solverx.service import SolverXService

router = APIRouter(prefix="/solverx", tags=["SolverX"])


def _sse_response(generator):
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            # Disable proxy buffering — Nginx/Cloudflare default to
            # buffering text/event-stream which kills the live status feel.
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/solve",
    summary="Solve a question with the multi-agent SolverX pipeline (SSE stream)",
)
async def solve(
    payload: SolveRequest,
    db: DBDep,
    current_user: CurrentVerifiedUser,
):
    service = SolverXService(db)
    gen = service.stream_solve(
        user_oid=current_user["_id"],
        question_text=payload.question_text,
        complexity_mode=payload.complexity_mode,
        conversation_id=payload.conversation_id,
        image_data_url=payload.image_data_url,
    )
    return _sse_response(gen)


@router.post(
    "/theory",
    summary="Explain a concept in *Theory* mode (SSE stream)",
)
async def theory(
    payload: TheoryRequest,
    db: DBDep,
    current_user: CurrentVerifiedUser,
):
    service = SolverXService(db)
    gen = service.stream_theory(
        user_oid=current_user["_id"],
        question_text=payload.question_text,
        complexity_mode=payload.complexity_mode,
        conversation_id=payload.conversation_id,
        image_data_url=payload.image_data_url,
    )
    return _sse_response(gen)


@router.get(
    "/conversations",
    response_model=ConversationList,
    summary="List the student's SolverX conversations",
)
async def list_conversations(
    db: DBDep, current_user: CurrentVerifiedUser,
) -> ConversationList:
    service = SolverXService(db)
    data = await service.list_conversations(current_user["_id"])
    return ConversationList(**data)


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetail,
    summary="Full transcript of one conversation",
)
async def get_conversation(
    conversation_id: str,
    db: DBDep,
    current_user: CurrentVerifiedUser,
) -> ConversationDetail:
    try:
        ObjectId(conversation_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found."
        ) from exc

    service = SolverXService(db)
    data = await service.get_conversation_detail(conversation_id, current_user["_id"])
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found."
        )
    return ConversationDetail(**data)
