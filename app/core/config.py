"""Application configuration — all values come from environment / .env file."""
from functools import lru_cache
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
    access_token_expire_minutes: int = 24 * 60

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

    # JSON log lines (set LOG_JSON=false for plain text while developing).
    log_json: bool = True

    # Bearer token for GET /metrics (read by Vigil). Unset = endpoint disabled.
    metrics_token: str | None = None
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
