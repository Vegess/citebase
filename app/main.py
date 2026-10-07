"""DocuMind — company docs RAG assistant.

Run locally:
    uvicorn app.main:app --reload

Interactive API docs at http://localhost:8000/docs
"""
import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from pathlib import Path

from app.core.config import get_settings
from app.core.database import SessionLocal
import app.models.models  # noqa: F401
from app.routes import auth, chat, documents, org, users
from app.routes.chat import limiter
from app.services.quota import get_usage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    force=True,
)

settings = get_settings()
logger = logging.getLogger("app.main")
active_provider_key = {
    "groq": settings.groq_api_key,
    "gemini": settings.google_api_key,
    "anthropic": settings.anthropic_api_key,
}.get(settings.llm_provider)
logger.info("llm_provider=%s key_loaded=%s", settings.llm_provider, bool(active_provider_key))
if not active_provider_key:
    # Loud on purpose: without a key every answer is the degraded local fallback.
    logger.error(
        "No API key for LLM_PROVIDER=%s. Answers will use the degraded local fallback "
        "until a key is set.",
        settings.llm_provider,
    )

app = FastAPI(
    title="DocuMind",
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    logger.exception("Unhandled server error for %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    logger.exception("Validation error for %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=422, content={"detail": "Validation error"})

# Comma-separated list, e.g. "http://localhost:5173,http://127.0.0.1:5173"
origins = [
    o.strip()
    for o in settings.cors_origins.split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(users.router)
app.include_router(chat.router)
app.include_router(org.router)


@app.get("/health")
def health():
    with SessionLocal() as db:
        questions_today = get_usage(db)
    return {
        "status": "ok",
        "questions_today": questions_today,
        "daily_cap": settings.daily_question_cap,
        "quota_remaining": max(0, settings.daily_question_cap - questions_today),
    }
