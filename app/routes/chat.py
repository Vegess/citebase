"""Chat route: ask a question, get a cited answer. Rate-limited per user."""
import json
import logging
import time
from itertools import chain
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from jose import jwt
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.config import get_settings
from app.core.security import get_current_user
from app.models.models import Conversation, ConversationMessage, User
from app.models.schemas import (
    AskRequest,
    AskResponse,
    Citation,
    ConversationDetailOut,
    ConversationMessageOut,
    ConversationOut,
)
from app.services.citations import select_citations
from app.services.generation import GroqRateLimitExceeded, generate_answer, stream_answer
from app.services.quota import release_question, reserve_question
from app.services.rag import retrieve_chunks

router = APIRouter(prefix="/chat", tags=["chat"])
limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger("app.routes.chat")
settings = get_settings()


def _user_ip_key(request: Request) -> str:
    ip = get_remote_address(request) or "unknown"
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return ip
    token = auth.split(" ", 1)[1]
    try:
        payload = jwt.get_unverified_claims(token)
    except Exception:
        return ip
    user_id = payload.get("sub")
    return f"{ip}:{user_id}" if user_id else ip


def _get_conversation_or_404(db: Session, conversation_id: str, user: User) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.org_id != user.org_id or conversation.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation


def _load_history(conversation: Conversation | None, db: Session) -> list[dict]:
    if conversation is None:
        return []

    rows = db.scalars(
        select(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == conversation.id,
            ConversationMessage.org_id == conversation.org_id,
        )
        .order_by(ConversationMessage.created_at.desc())
        .limit(6)
    ).all()
    return [{"role": msg.role, "content": msg.content} for msg in reversed(rows)]


DEFAULT_TITLE = "New conversation"


def _title_from_question(question: str) -> str:
    title = " ".join(question.split())
    return (title[:77] + "...") if len(title) > 80 else (title or DEFAULT_TITLE)


def _name_if_untitled(conversation: Conversation, question: str) -> None:
    # The UI creates the conversation before the first question is asked, so
    # the title must be filled in here rather than only at creation time.
    if not conversation.title or conversation.title == DEFAULT_TITLE:
        conversation.title = _title_from_question(question)


def _ensure_conversation(body: AskRequest, user: User, db: Session) -> Conversation | None:
    conversation_id = getattr(body, "conversation_id", None)
    if not conversation_id:
        return None
    return _get_conversation_or_404(db, conversation_id, user)


@router.post("/conversations", response_model=ConversationOut)
def create_conversation(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conversation = Conversation(org_id=user.org_id, user_id=user.id, title="New conversation")
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return ConversationOut(id=conversation.id, title=conversation.title, created_at=conversation.created_at, updated_at=conversation.updated_at)


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conversations = db.scalars(
        select(Conversation)
        .where(Conversation.user_id == user.id, Conversation.org_id == user.org_id)
        .order_by(Conversation.updated_at.desc(), Conversation.created_at.desc())
    ).all()
    return [ConversationOut(id=c.id, title=c.title, created_at=c.created_at, updated_at=c.updated_at) for c in conversations]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailOut)
def get_conversation(conversation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conversation = _get_conversation_or_404(db, conversation_id, user)
    return ConversationDetailOut(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[
            ConversationMessageOut(
                id=msg.id,
                role=msg.role,
                content=msg.content,
                citations=[
                    Citation(filename=c["filename"], chunk_index=c["chunk_index"], n=c.get("n"))
                    for c in json.loads(msg.citations)
                ] if msg.citations else None,
                created_at=msg.created_at,
            )
            for msg in conversation.messages
        ],
    )


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conversation = _get_conversation_or_404(db, conversation_id, user)
    db.delete(conversation)
    db.commit()
    return {"deleted": True}


@router.post("/ask", response_model=AskResponse)
@limiter.limit("20/minute", key_func=_user_ip_key)
def ask(
    request: Request,
    body: AskRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start = time.perf_counter()
    conversation = _ensure_conversation(body, user, db)
    chunks = retrieve_chunks(org_id=user.org_id, query=body.question, top_k=settings.retrieval_top_k)
    history = _load_history(conversation, db)

    reserve_question(db, user.id)
    try:
        answer = generate_answer(body.question, chunks, prior_turns=history)
    except GroqRateLimitExceeded:
        release_question(db, user.id)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="The demo is busy right now. Please try again in a moment.",
            headers={"Retry-After": "2"},
        )

    if conversation is None:
        conversation = Conversation(org_id=user.org_id, user_id=user.id, title=DEFAULT_TITLE)
        db.add(conversation)
        db.flush()
    _name_if_untitled(conversation, body.question)
    used = select_citations(answer, chunks)

    db.add(
        ConversationMessage(
            conversation_id=conversation.id,
            org_id=user.org_id,
            user_id=user.id,
            role="user",
            content=body.question,
        )
    )
    db.add(
        ConversationMessage(
            conversation_id=conversation.id,
            org_id=user.org_id,
            user_id=user.id,
            role="assistant",
            content=answer,
            citations=json.dumps(used),
        )
    )
    conversation.updated_at = datetime.now(timezone.utc)
    db.commit()

    citations = [Citation(**c) for c in used]
    latency_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "chat.ask completed user_id=%s org_id=%s latency_ms=%s retrieved_chunks=%s",
        user.id,
        user.org_id,
        latency_ms,
        len(chunks),
    )
    return AskResponse(answer=answer, citations=citations)


@router.post("/ask/stream")
@limiter.limit("20/minute", key_func=_user_ip_key)
def ask_stream(
    request: Request,
    body: AskRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = user.id
    org_id = user.org_id
    conversation = _ensure_conversation(body, user, db)
    chunks = retrieve_chunks(org_id=user.org_id, query=body.question, top_k=settings.retrieval_top_k)
    history = _load_history(conversation, db)
    reserve_question(db, user_id)

    if conversation is None:
        conversation = Conversation(org_id=user.org_id, user_id=user.id, title=DEFAULT_TITLE)
        db.add(conversation)
        db.flush()
        db.refresh(conversation)
    _name_if_untitled(conversation, body.question)
    db.commit()
    conversation_id = conversation.id
    answer_stream = stream_answer(body.question, chunks, prior_turns=history)
    try:
        first_chunk = next(answer_stream)
    except GroqRateLimitExceeded:
        release_question(db, user_id)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="The demo is busy right now. Please try again in a moment.",
            headers={"Retry-After": "2"},
        )

    def event_generator():
        start = time.perf_counter()
        full_answer = ""
        local_db = SessionLocal()

        try:
            local_db.add(
                ConversationMessage(
                    conversation_id=conversation_id,
                    org_id=org_id,
                    user_id=user_id,
                    role="user",
                    content=body.question,
                )
            )
            local_db.flush()

            for chunk in chain([first_chunk], answer_stream):
                full_answer += chunk
                yield f"data: {json.dumps({'text': chunk})}\n\n"

            citations = select_citations(full_answer, chunks)
            yield f"data: {json.dumps({'citations': citations})}\n\n"
            yield "data: [DONE]\n\n"

            local_db.add(
                ConversationMessage(
                    conversation_id=conversation_id,
                    org_id=org_id,
                    user_id=user_id,
                    role="assistant",
                    content=full_answer,
                    citations=json.dumps(citations),
                )
            )
            local_db.commit()

            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "chat.ask.stream completed user_id=%s org_id=%s latency_ms=%s retrieved_chunks=%s",
                user_id,
                org_id,
                latency_ms,
                len(chunks),
            )
        finally:
            local_db.close()

    return StreamingResponse(event_generator(), media_type="text/event-stream")
