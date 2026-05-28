from fastapi import APIRouter, status

from core.dependencies import CurrentVerifiedUser, DBDep
from modules.profile.schema import (
    ProfileCreateRequest,
    ProfileResponse,
    ProfileUpdateRequest,
)
from modules.profile.service import ProfileService

router = APIRouter(prefix="/profile", tags=["Profile"])


@router.post(
    "/create",
    response_model=ProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create the student profile for the current user",
)
async def create_profile(
    payload: ProfileCreateRequest,
    current_user: CurrentVerifiedUser,
    db: DBDep,
) -> ProfileResponse:
    return await ProfileService(db).create(current_user["_id"], payload)


@router.get(
    "/me",
    response_model=ProfileResponse,
    summary="Get the current user's profile",
)
async def my_profile(
    current_user: CurrentVerifiedUser,
    db: DBDep,
) -> ProfileResponse:
    return await ProfileService(db).get_mine(current_user["_id"])


@router.put(
    "/update",
    response_model=ProfileResponse,
    summary="Update one or more profile fields",
)
async def update_profile(
    payload: ProfileUpdateRequest,
    current_user: CurrentVerifiedUser,
    db: DBDep,
) -> ProfileResponse:
    return await ProfileService(db).update(current_user["_id"], payload)


@router.post(
    "/tours/{tour_slug}/complete",
    response_model=ProfileResponse,
    summary="Mark a product tour as completed for the current user",
)
async def complete_tour(
    tour_slug: str,
    current_user: CurrentVerifiedUser,
    db: DBDep,
) -> ProfileResponse:
    return await ProfileService(db).complete_tour(current_user["_id"], tour_slug)
