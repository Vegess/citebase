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
    groq_model: str = "llama-3.3-70b-versatile"
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
    chroma_persist_dir: str = "./chroma_data"
    embedding_model: str = "all-MiniLM-L6-v2"
    claude_model: str = "claude-sonnet-4-6"
    max_upload_mb: int = 20
    max_document_chars: int = 200_000
    retrieval_top_k: int = 3
    max_prior_turns: int = 2
    max_context_chars: int = 8_000
    daily_question_cap: int = 70
    per_user_daily_cap: int = 10
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
