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
from slowapi.util import get_remote_address
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_user, require_role, role_rank
from app.models.models import Document, DocumentChunk, DocumentEvent, User
from app.models.schemas import DocumentEventOut, DocumentOut
from app.routes.chat import limiter
from app.services import audit, extract, ingestion, jobs, lifecycle

router = APIRouter(prefix="/documents", tags=["documents"])
settings = get_settings()
logger = logging.getLogger("app.routes.documents")

# Browsers label files inconsistently (.md is often "" or octet-stream), so the
# type is decided from the bytes; this list only turns away obvious mismatches.
ALLOWED_TYPES = {
    "application/pdf", "text/plain", "text/markdown", "text/x-markdown", "application/octet-stream",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _sanitize_filename(name: str | None) -> str:
    value = (name or "untitled").replace("\\", "/")
    value = value.rsplit("/", 1)[-1]
    value = value.replace("\x00", "")
    value = re.sub(r"[\x00-\x1f\x7f]+", "", value)
    value = value.strip(" .")
    return value or "untitled"


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
        raise HTTPException(status_code=415, detail="Upload a PDF, Word (.docx), Markdown or plain-text file.")

    raw = file.file.read()
    try:
        text = extract.extract(raw, file.filename or "")
    except extract.ExtractionError as exc:
        status = 415 if "Upload a PDF" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc))
    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail="No text could be read from this file. Scanned PDFs (images of pages) aren't supported yet.",
        )

    truncated = len(text) > settings.max_document_chars
    if truncated:
        text = text[: settings.max_document_chars]

    return _create_document(db, user, _sanitize_filename(file.filename), text, truncated, background_tasks)


def _create_document(db: Session, user: User, safe_name: str, text: str, truncated: bool,
                     background_tasks: BackgroundTasks) -> Document:
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


SAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "samples")


@router.post("/samples", response_model=list[DocumentOut], status_code=201)
def load_samples(background_tasks: BackgroundTasks, user: User = Depends(require_role("MEMBER")),
                 db: Session = Depends(get_db)):
    """Add the Northwind Freight demo policies, so a new workspace can try
    questions straight away. Files already in the workspace are skipped."""
    existing = set(db.scalars(select(Document.filename).where(Document.org_id == user.org_id)))
    created = []
    for name in sorted(os.listdir(SAMPLES_DIR)):
        if not name.endswith(".txt") or name in existing:
            continue
        with open(os.path.join(SAMPLES_DIR, name), encoding="utf-8") as fh:
            text = fh.read()
        created.append(_create_document(db, user, name, text, False, background_tasks))
    return created


@router.get("/passage")
def read_passage(chunk_index: int, doc_id: str | None = None, filename: str | None = None,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The exact text behind a citation, plus a little of what surrounds it."""
    query = select(Document).where(Document.org_id == user.org_id)
    if doc_id:
        query = query.where(Document.id == doc_id)
    elif filename:
        query = query.where(Document.filename == filename).order_by(Document.created_at.desc())
    else:
        raise HTTPException(status_code=400, detail="doc_id or filename is required")
    doc = db.scalars(query).first()
    if doc is None:
        raise HTTPException(status_code=404, detail="That document is no longer in this workspace.")
    rows = {
        c.chunk_index: c.text
        for c in db.scalars(select(DocumentChunk).where(
            DocumentChunk.doc_id == doc.id, DocumentChunk.org_id == user.org_id,
            DocumentChunk.chunk_index.in_([chunk_index - 1, chunk_index, chunk_index + 1])))
    }
    if chunk_index not in rows:
        raise HTTPException(status_code=404, detail="That passage has changed since the answer was written.")
    return {
        "doc_id": doc.id, "filename": doc.filename, "chunk_index": chunk_index, "text": rows[chunk_index],
        "before": rows.get(chunk_index - 1), "after": rows.get(chunk_index + 1), "num_chunks": doc.num_chunks,
    }


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
