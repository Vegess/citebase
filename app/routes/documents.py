"""Document routes: upload (PDF or txt), list, status, history, delete — all org-scoped.

Upload extracts text immediately (so an unreadable file is rejected while the
user is still looking), then queues the slow part — chunking and embedding —
as a durable job. Status moves through app/services/lifecycle.py.
"""
import io
import logging
import os
import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from slowapi.util import get_remote_address
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_user, require_role, role_rank
from app.models.models import Document, DocumentChunk, DocumentEvent, User
from app.models.schemas import DocumentEventOut, DocumentOut
from app.routes.chat import limiter
from app.services import audit, ingestion, jobs, lifecycle

router = APIRouter(prefix="/documents", tags=["documents"])
settings = get_settings()
logger = logging.getLogger("app.routes.documents")

ALLOWED_TYPES = {"application/pdf", "text/plain"}
_INVISIBLE = re.compile(r"[​-‍⁠﻿]")


def _sanitize_filename(name: str | None) -> str:
    value = (name or "untitled").replace("\\", "/")
    value = value.rsplit("/", 1)[-1]
    value = value.replace("\x00", "")
    value = re.sub(r"[\x00-\x1f\x7f]+", "", value)
    value = value.strip(" .")
    return value or "untitled"


def _extract_text(raw: bytes) -> str:
    if raw.startswith(b"%PDF-"):
        try:
            reader = PdfReader(io.BytesIO(raw))
            if reader.is_encrypted:
                raise HTTPException(status_code=422, detail="This PDF is password-protected. Upload an unlocked copy.")
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except PdfReadError:
            raise HTTPException(status_code=422, detail="This PDF looks damaged and couldn't be read.")
    else:
        text = raw.decode("utf-8", errors="replace")
    return _INVISIBLE.sub("", text)


def _schedule(background_tasks: BackgroundTasks) -> None:
    if settings.worker_mode == "inline":
        background_tasks.add_task(jobs.drain)
    else:
        jobs.wake_worker()


@router.post("", response_model=DocumentOut, status_code=201)
@limiter.limit("20/minute", key_func=lambda request: f"{get_remote_address(request)}:{request.headers.get('authorization', '').split('Bearer ', 1)[-1][:32]}")
def upload_document(
    request: Request,
    file: UploadFile,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_role("MEMBER")),
    db: Session = Depends(get_db),
):
    file.file.seek(0, os.SEEK_END)
    size = file.file.tell()
    file.file.seek(0)
    if size > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.max_upload_mb} MB limit")

    if file.content_type and file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="Only PDF and plain text files are supported")

    raw = file.file.read()
    if not raw.startswith(b"%PDF-"):
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=415, detail="Only PDF and plain text files are supported")

    text = _extract_text(raw)
    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail="No text could be read from this file. Scanned PDFs (images of pages) aren't supported yet.",
        )

    truncated = len(text) > settings.max_document_chars
    if truncated:
        text = text[: settings.max_document_chars]

    safe_name = _sanitize_filename(file.filename)
    doc = Document(
        org_id=user.org_id,
        uploaded_by=user.id,
        filename=safe_name,
        status=lifecycle.QUEUED,
        char_count=len(text),
        truncated=truncated,
    )
    db.add(doc)
    db.flush()
    lifecycle.record_created(db, doc, detail="truncated" if truncated else None)
    jobs.enqueue(db, ingestion.KIND, {"doc_id": doc.id, "org_id": user.org_id, "text": text})
    audit.record(
        db, org_id=user.org_id, actor_id=user.id, action="document.uploaded",
        target_type="document", target_id=doc.id, details={"filename": safe_name, "truncated": truncated},
    )
    db.commit()
    db.refresh(doc)
    _schedule(background_tasks)
    return doc


def _own_doc_or_404(db: Session, doc_id: str, user: User) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None or doc.org_id != user.org_id:
        # 404 either way — don't reveal that the doc exists in another org
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document_status(doc_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _own_doc_or_404(db, doc_id, user)


@router.get("/{doc_id}/events", response_model=list[DocumentEventOut])
def get_document_events(doc_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doc = _own_doc_or_404(db, doc_id, user)
    return db.scalars(
        select(DocumentEvent).where(DocumentEvent.doc_id == doc.id).order_by(DocumentEvent.id)
    ).all()


@router.get("", response_model=list[DocumentOut])
def list_documents(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # org_id comes from the authenticated user, never from the request
    return db.scalars(
        select(Document).where(Document.org_id == user.org_id).order_by(Document.created_at.desc())
    ).all()


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doc = db.scalar(
        select(Document).where(Document.id == doc_id, Document.org_id == user.org_id).with_for_update()
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.uploaded_by != user.id and role_rank(user.role) < role_rank("ADMIN"):
        raise HTTPException(status_code=403, detail="Only the uploader or an admin can remove this document.")

    # One transaction: the document, its vectors and its history go together.
    # (A running ingest job notices the document is gone and stops.)
    db.execute(delete(DocumentChunk).where(DocumentChunk.doc_id == doc.id))
    db.execute(delete(DocumentEvent).where(DocumentEvent.doc_id == doc.id))
    audit.record(
        db, org_id=user.org_id, actor_id=user.id, action="document.deleted",
        target_type="document", target_id=doc.id, details={"filename": doc.filename},
    )
    db.delete(doc)
    db.commit()
