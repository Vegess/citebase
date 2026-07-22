"""DocuMind — company docs RAG assistant.

Run locally:
    uvicorn app.main:app --reload

Interactive API docs at http://localhost:8000/docs
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.routes import auth, chat, documents
from app.routes.chat import limiter

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s %(levelname)s %(name)s %(message)s "
        "user_id=%(user_id)s org_id=%(org_id)s latency_ms=%(latency_ms)s "
        "retrieved_chunks=%(retrieved_chunks)s"
    ),
)

app = FastAPI(title="DocuMind", version="0.1.0")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — restrict to your frontend origin. Never use "*" with credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(chat.router)


@app.get("/health")
def health():
    return {"status": "ok"}
