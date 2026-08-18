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
from app.core.database import Base, engine
import app.models.models  # noqa: F401
from app.routes import auth, chat, documents, users
from app.routes.chat import limiter

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

app = FastAPI(
    title="DocuMind",
    version="0.1.0",
    docs_url=None if settings.environment.lower() == "production" or settings.debug else "/docs",
    redoc_url=None if settings.environment.lower() == "production" or settings.debug else "/redoc",
    openapi_url=None if settings.environment.lower() == "production" or settings.debug else "/openapi.json",
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

# Ensure database schema exists on startup.
Base.metadata.create_all(bind=engine)

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


@app.get("/health")
def health():
    return {"status": "ok"}
