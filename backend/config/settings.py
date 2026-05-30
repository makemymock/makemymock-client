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

    # ---- SolverX (Google Vertex AI / Gemini) ----
    # Auth is handled by Application Default Credentials (ADC) — the
    # SDK auto-discovers `gcloud auth application-default login` on dev
    # machines, and a runtime-bound identity (Cloud Run / GKE Workload
    # Identity) in production. No JSON key needs to live on disk.
    #
    # Four model slots are configured because SolverX routes by mode +
    # complexity AND treats diagrams as a separate concern:
    #   * SIMPLE solve / easy theory  → FLASH       (cheap, fast)
    #   * Plan stage in DEEP modes    → FLASH_LITE  (cheapest, structured JSON only)
    #   * Deep solver / theory tutor  → PRO         (most capable, slower)
    #   * Diagram draft + polish      → DIAGRAM     (tuned separately;
    #     SVG generation is more layout than reasoning, so Flash is
    #     cheap and fast enough — but kept as its own slot so it can be
    #     swapped without touching the solver model)
    GCP_PROJECT_ID: str = ""
    GCP_LOCATION: str = "global"
    GEMINI_MODEL_PRO: str = "gemini-3.1-pro-preview"
    GEMINI_MODEL_FLASH: str = "gemini-3.5-flash"
    GEMINI_MODEL_FLASH_LITE: str = "gemini-3.1-flash-lite"
    GEMINI_MODEL_DIAGRAM: str = "gemini-3.5-flash"

    # ---- JEE Questions catalog (adaptive_practice DB on a separate cluster) ----
    # The PYQ questions live in a separate MongoDB cluster uploaded by
    # jee_mains_pyqs_data_base/upload_to_mongo.py. A second Motor client
    # connects to PYQ_MONGO_URI and reads from JEE_QUESTIONS_DB_NAME.
    PYQ_MONGO_URI: str = ""
    JEE_QUESTIONS_DB_NAME: str = "adaptive_practice"

    # ---- JEE Recommender agentic layer (Vertex AI / Gemini) ----
    # Two model slots — same Vertex AI / ADC auth as SolverX:
    #   FAST  → QuestionSelectorAgent: pure selection, thinking disabled
    #   HEAVY → SessionPlannerAgent / DiagnosisAgent: tool-use + reasoning
    RECOMMENDER_MODEL_FAST: str = "gemini-2.0-flash-lite"
    RECOMMENDER_MODEL_HEAVY: str = "gemini-2.5-flash"

    # ---- Groq (kept for rollback reference — no longer active) ----
    GROQ_API_KEY: str = ""
    GROQ_MODEL_FAST: str = "llama-3.3-70b-versatile"
    GROQ_MODEL_HEAVY: str = "qwen/qwen3-32b"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
