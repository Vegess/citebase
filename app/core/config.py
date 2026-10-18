"""Application configuration — all values come from environment / .env file."""
from functools import lru_cache
from typing import Literal
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # App
    environment: str = "development"
    debug: bool = False

    # LLM provider
    llm_provider: str = "groq"  # "groq" | "gemini" | "anthropic"
    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-120b"  # llama-3.3-70b-versatile was retired by Groq
    google_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"

    # Anthropic
    anthropic_api_key: str | None = None

    # Database
    database_url: str = "sqlite:///./documind.db"

    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    # Short-lived: the browser renews it from the httpOnly session cookie.
    access_token_expire_minutes: int = 30
    session_days: int = 30
    # Path the browser sees for session endpoints (the frontend proxies /api/* here).
    session_cookie_path: str = "/api/auth"
    # Password-reset emails (Resend). Without a key, admins hand out reset links instead.
    resend_api_key: str | None = None
    brevo_api_key: str | None = None
    mail_from: str = "Citebase <no-reply@citebase.app>"

    # RAG
    chroma_persist_dir: str = "./chroma_data"  # unused since vectors moved to the database; kept so old .env files still load
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    claude_model: str = "claude-sonnet-4-6"
    max_upload_mb: int = 20
    # ~60 pages of dense text. Longer files are cut here and flagged `truncated`.
    max_document_chars: int = 200_000
    retrieval_top_k: int = 6
    # Vector + keyword search fused with reciprocal-rank fusion.
    hybrid_search: bool = True
    max_prior_turns: int = 2
    max_context_chars: int = 8_000
    # Budget for whole-document tasks (summarise / review / compare). ~4k tokens,
    # which stays inside free-tier per-minute token limits.
    whole_doc_chars: int = 16_000
    daily_question_cap: int = 70      # whole deployment (protects the LLM bill)
    per_org_daily_cap: int = 50
    per_user_daily_cap: int = 10

    # Background jobs: "thread" runs a worker inside the API process (Render),
    # "inline" drains the queue after each request (tests), "off" for a
    # separate worker process.
    worker_mode: str = "thread"

    # Load the embedding model in the background at startup (off in tests).
    warm_embedder: bool = True

    # Sign in with Google / GitHub. A provider is enabled only when both its
    # client id and secret are set. API_PUBLIC_URL is this API's public base
    # URL (the OAuth callback lives there); FRONTEND_URL is where users land.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    github_client_id: str | None = None
    github_client_secret: str | None = None
    api_public_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:5173"

    # Invite-only launch. "waitlist": new accounts need an approved access
    # request (team invites still work, existing users can always sign in).
    signup_mode: Literal["open", "waitlist"] = "open"
    # Comma-separated emails that may review access requests at /admin/access.
    platform_admin_emails: str = ""

    # JSON log lines (set LOG_JSON=false for plain text while developing).
    log_json: bool = True

    # Bearer token for GET /metrics (read by Vigil). Unset = endpoint disabled.
    metrics_token: str | None = None
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    @property
    def platform_admins(self) -> set[str]:
        return {e.strip().lower() for e in self.platform_admin_emails.split(",") if e.strip()}

    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
