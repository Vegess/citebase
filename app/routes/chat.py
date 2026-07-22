"""Chat route: ask a question, get a cited answer. Rate-limited per user
(security concern #6 — protects your Anthropic bill)."""
import logging
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import ChatMessage, User
from app.models.schemas import AskRequest, AskResponse, Citation
from app.services.generation import generate_answer, stream_answer
from app.services.rag import retrieve_chunks

router = APIRouter(prefix="/chat", tags=["chat"])
limiter = Limiter(key_func=get_remote_address)


def _load_history(user: User, db: Session) -> list[dict]:
    last_messages = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.user_id == user.id, ChatMessage.org_id == user.org_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(6)
    ).all()
    return [{"role": msg.role, "content": msg.content} for msg in reversed(last_messages)]


logger = logging.getLogger("app.routes.chat")


@router.post("/ask", response_model=AskResponse)
@limiter.limit("20/minute")
def ask(
    request: Request,
    body: AskRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start = time.perf_counter()
    chunks = retrieve_chunks(org_id=user.org_id, query=body.question, top_k=5)
    history = _load_history(user, db)

    answer = generate_answer(body.question, chunks, prior_turns=history)

    db.add(ChatMessage(org_id=user.org_id, user_id=user.id, role="user", content=body.question))
    db.add(ChatMessage(org_id=user.org_id, user_id=user.id, role="assistant", content=answer))
    db.commit()

    citations = [Citation(filename=c["filename"], chunk_index=c["chunk_index"]) for c in chunks]
    latency_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "chat.ask completed",
        extra={
            "user_id": user.id,
            "org_id": user.org_id,
            "latency_ms": latency_ms,
            "retrieved_chunks": len(chunks),
        },
    )
    return AskResponse(answer=answer, citations=citations)


@router.post("/ask/stream")
@limiter.limit("20/minute")
def ask_stream(
    request: Request,
    body: AskRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chunks = retrieve_chunks(org_id=user.org_id, query=body.question, top_k=5)
    history = _load_history(user, db)

    def event_generator():
        start = time.perf_counter()
        full_answer = ""
        for chunk in stream_answer(body.question, chunks, prior_turns=history):
            full_answer += chunk
            yield f"data: {chunk}\n\n"

        db.add(ChatMessage(org_id=user.org_id, user_id=user.id, role="user", content=body.question))
        db.add(ChatMessage(org_id=user.org_id, user_id=user.id, role="assistant", content=full_answer))
        db.commit()

        latency_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "chat.ask.stream completed",
            extra={
                "user_id": user.id,
                "org_id": user.org_id,
                "latency_ms": latency_ms,
                "retrieved_chunks": len(chunks),
            },
        )

    return StreamingResponse(event_generator(), media_type="text/event-stream")
