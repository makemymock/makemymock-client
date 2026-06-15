"""Pattern-miner read API.

Read-only views over the mined catalog: which chapters have patterns, the
patterns in a chapter, and the questions each pattern covers. The mining that
produces this data runs offline in `jobs/`.

These routes read from the PYQ cluster (`modules.pattern_miner.db`), not the
primary `DBDep` database — that's where the miner writes. Auth still resolves
against the primary DB through `CurrentVerifiedUser`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from core.dependencies import CurrentVerifiedUser
from modules.pattern_miner.db import get_pattern_miner_db
from modules.pattern_miner.schema import (
    ChapterCoverageList,
    PatternDetail,
    PatternList,
)
from modules.pattern_miner.service import PatternMinerService

router = APIRouter(prefix="/pattern-miner", tags=["Pattern Miner"])


@router.get(
    "/chapters",
    response_model=ChapterCoverageList,
    summary="Chapters that have mined patterns, with coverage counts",
)
async def list_chapters(current_user: CurrentVerifiedUser) -> ChapterCoverageList:
    service = PatternMinerService(get_pattern_miner_db())
    data = await service.list_chapter_coverage()
    return ChapterCoverageList(**data)


@router.get(
    "/chapters/{chapter}/patterns",
    response_model=PatternList,
    summary="All patterns mined for one chapter (largest bucket first)",
)
async def list_chapter_patterns(
    chapter: str, current_user: CurrentVerifiedUser,
) -> PatternList:
    service = PatternMinerService(get_pattern_miner_db())
    data = await service.list_patterns_for_chapter(chapter)
    return PatternList(**data)


@router.get(
    "/patterns/{pattern_id}",
    response_model=PatternDetail,
    summary="One pattern plus the questions assigned to it",
)
async def get_pattern(
    pattern_id: str, current_user: CurrentVerifiedUser,
) -> PatternDetail:
    service = PatternMinerService(get_pattern_miner_db())
    data = await service.get_pattern_detail(pattern_id)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pattern not found."
        )
    return PatternDetail(**data)
