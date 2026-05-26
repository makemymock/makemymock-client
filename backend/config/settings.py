from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ---- App ----
    APP_NAME: str = "MakeMyMock"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    API_V1_PREFIX: str = "/api/v1"

    # ---- MongoDB ----
    MONGO_URI: str
    MONGO_DB_NAME: str = "makemymock"

    # ---- JWT ----
    JWT_SECRET_KEY: str = Field(..., min_length=16)
    JWT_REFRESH_SECRET_KEY: str = Field(..., min_length=16)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ---- SMTP (fallback for local dev) ----
    SMTP_HOST: str
    SMTP_PORT: int = 587
    SMTP_EMAIL: str
    SMTP_PASSWORD: str
    SMTP_FROM_NAME: str = "MakeMyMock"
    SMTP_USE_TLS: bool = True

    # ---- Brevo HTTPS email API (recommended for cloud deploys) ----
    # When BREVO_API_KEY is set we route email through Brevo's REST API on
    # port 443. Most cloud hosts (Railway, Render, Heroku, Vercel) block
    # or throttle outbound port 587, so SMTP to Gmail fails with a
    # connect timeout. Brevo is reachable from any host. Leave blank to
    # keep using the SMTP path.
    BREVO_API_KEY: str = ""

    # ---- OTP ----
    OTP_EXPIRY_MINUTES: int = 5
    OTP_MAX_ATTEMPTS: int = 5
    OTP_RESEND_COOLDOWN_SECONDS: int = 60

    # ---- SolverX (Groq) ----
    # Leave GROQ_API_KEY blank in env to disable SolverX in dev.
    # GROQ_MODEL is overridable so we can swap models without code
    # changes. Llama 4 Scout is multimodal — when we add image upload to
    # the SolverX UI later, the same model handles it.
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "meta-llama/llama-4-scout-17b-16e-instruct"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
