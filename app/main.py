"""DocuMind — company docs RAG assistant.

Run locally:
    uvicorn app.main:app --reload

Interactive API docs at http://localhost:8000/docs
"""
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from pathlib import Path

from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from secrets import compare_digest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.logging_setup import configure_logging, recent_logs
from app.models.models import Document, DocumentChunk, Job
from app.routes import auth, chat, documents, insights, oauth, org, users
from app.routes.chat import limiter
from app.services import conflicts, ingestion, summaries  # noqa: F401 — register job handlers
from app.services import jobs, metrics, rag
from app.services.quota import get_usage

settings = get_settings()
configure_logging(json_logs=settings.log_json)
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

STARTED_AT = datetime.now(timezone.utc).isoformat()
# Render sets RENDER_GIT_COMMIT; a change in this value is how Vigil sees a deploy.
COMMIT = os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT") or "unknown"


def _warm_embedder() -> None:
    """Load the embedding model at startup, off the request path, so the first
    question after a cold start does not pay for it."""
    try:
        started = time.perf_counter()
        list(rag.get_embedder().embed(["warm up"]))
        logger.info("Embedding model ready in %.1fs", time.perf_counter() - started)
    except Exception:  # noqa: BLE001 — a failed warm-up is retried on first use
        logger.exception("Embedding model warm-up failed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    worker = None
    if settings.worker_mode == "thread":
        worker = jobs.Worker()
        worker.start()
    if settings.warm_embedder:
        threading.Thread(target=_warm_embedder, name="embedder-warmup", daemon=True).start()
    yield
    if worker:
        worker.stop()


app = FastAPI(
    lifespan=lifespan,
    title="DocuMind",
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.middleware("http")
async def record_request_metrics(request: Request, call_next):
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        if not request.url.path.startswith(("/metrics", "/ping")):
            metrics.record_request(status_code, int((time.perf_counter() - start) * 1000))


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
app.include_router(oauth.router)
# Before documents: /documents/suggestions must not be captured by /documents/{doc_id}.
app.include_router(insights.router)
app.include_router(documents.router)
app.include_router(users.router)
app.include_router(chat.router)
app.include_router(org.router)


@app.get("/ping")
def ping():
    """Liveness only. Touches no database, so an uptime monitor hitting it every
    few minutes keeps the server awake without keeping Neon awake."""
    return {"status": "ok"}


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


# ---- Observability (read by Vigil) ----
_bearer = HTTPBearer(auto_error=False)


def require_metrics_token(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    # Disabled unless METRICS_TOKEN is set; 404 so the endpoint isn't advertised.
    if not settings.metrics_token:
        raise HTTPException(status_code=404, detail="Not Found")
    if credentials is None or not compare_digest(credentials.credentials, settings.metrics_token):
        raise HTTPException(status_code=401, detail="Invalid metrics token")


@app.get("/metrics", dependencies=[Depends(require_metrics_token)])
def read_metrics():
    with SessionLocal() as db:
        docs_by_status = dict(db.execute(select(Document.status, func.count()).group_by(Document.status)).all())
        chunks_total = db.scalar(select(func.count()).select_from(DocumentChunk)) or 0
        jobs_by_status = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
        questions_today = get_usage(db)
    model = {
        "groq": settings.groq_model, "gemini": settings.gemini_model, "anthropic": settings.claude_model,
    }.get(settings.llm_provider)
    return {
        **metrics.snapshot(),
        "started_at": STARTED_AT,
        "commit": COMMIT,
        "llm_provider": settings.llm_provider,
        "llm_model": model,
        "llm_key_loaded": bool(active_provider_key),
        "documents_total": sum(docs_by_status.values()),
        "documents_by_status": docs_by_status,
        "chunks_total": chunks_total,
        "jobs_by_status": jobs_by_status,
        "questions_today": questions_today,
    }


@app.get("/metrics/logs", dependencies=[Depends(require_metrics_token)])
def read_recent_logs(since: str | None = None, level: str | None = None, contains: str | None = None,
                     limit: int = 100):
    return recent_logs.snapshot(since=since, level=level, contains=contains, limit=max(1, min(limit, 500)))
