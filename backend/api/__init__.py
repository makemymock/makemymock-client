from fastapi import APIRouter

from modules.authentication.controller import router as auth_router
from modules.profile.controller import router as profile_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(profile_router)
