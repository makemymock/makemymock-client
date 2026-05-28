from fastapi import APIRouter

from modules.authentication.controller import router as auth_router
from modules.battle.controller import router as battle_router
from modules.mock_test.controller import router as mock_test_router
from modules.profile.controller import router as profile_router
from modules.recommender.controller import router as recommender_router
from modules.solverx.controller import router as solverx_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(profile_router)
api_router.include_router(mock_test_router)
api_router.include_router(battle_router)
api_router.include_router(solverx_router)
api_router.include_router(recommender_router)
