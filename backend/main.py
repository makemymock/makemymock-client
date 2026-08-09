import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from api import api_router
from config.database import close_mongo_connection, connect_to_mongo
from config.redis import close_redis_connection, connect_to_redis
from config.settings import settings
from core.exceptions import AppException
from modules.battle.matchmaker import init_matchmaker_redis
from modules.pattern_learning.db import (
    close_client as close_pattern_learning_db,
    ensure_indexes as ensure_pattern_learning_indexes,
)
from modules.pattern_miner.db import close_client as close_pattern_miner_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await connect_to_mongo()
    await connect_to_redis()
    init_matchmaker_redis()
    try:
        await ensure_pattern_learning_indexes()
    except Exception as exc:  # noqa: BLE001 — a PYQ-cluster blip must not block boot
        logger.warning("pattern_learning index init skipped: %s", exc)
    try:
        yield
    finally:
        await close_redis_connection()
        await close_mongo_connection()
        await close_pattern_miner_db()
        await close_pattern_learning_db()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        description="Authentication & user-onboarding backend for MakeMyMock.",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://www.makemymock.com",
            "https://makemymock.com",
            "https://makemymock-client-git-main-makemymock-8748s-projects.vercel.app",
        ],
        # Vercel mints a fresh hash-suffixed URL per preview deploy, so those
        # are matched by pattern rather than listed one by one.
        allow_origin_regex=r"https://makemymock-client-[a-z0-9]+-makemymock-8748s-projects\.vercel\.app",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.exception_handler(AppException)
    async def app_exception_handler(_: Request, exc: AppException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(ValidationError)
    async def pydantic_validation_handler(_: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": exc.errors()},
        )

    @app.get("/", tags=["Health"])
    async def root() -> dict:
        return {"status": "ok", "app": settings.APP_NAME, "env": settings.APP_ENV}

    @app.get("/health", tags=["Health"])
    async def health() -> dict:
        return {"status": "healthy"}

    return app


app = create_app()
