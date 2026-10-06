"""Document routes: upload (PDF or txt), list, delete — all org-scoped."""
import io
import logging
import os
import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile
from pypdf import PdfReader
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal, get_db
from app.core.security import get_current_user, require_role, role_rank
from app.models.models import Document, User
from app.models.schemas import DocumentOut
from app.routes.chat import limiter
from app.services import audit
from app.services.rag import delete_document_chunks, ingest_document

router = APIRouter(prefix="/documents", tags=["documents"])
settings = get_settings()
logger = logging.getLogger("app.routes.documents")


def _process_document_background(doc_id: str, org_id: str, filename: str, text: str) -> None:
    db = SessionLocal()
    try:
        num_chunks = ingest_document(doc_id, org_id, filename, text)
        doc = db.get(Document, doc_id)
        if doc is None:
            return
        doc.num_chunks = num_chunks
        doc.status = "ready" if num_chunks > 0 else "failed"
        db.commit()
    except Exception:
        # Never fail silently: a swallowed ingest error is how every upload
        # ends up "failed" with nothing in the logs to say why.
        logger.exception("Document ingestion failed doc_id=%s org_id=%s", doc_id, org_id)
        db.rollback()
        doc = db.get(Document, doc_id)
        if doc is not None:
            doc.status = "failed"
            db.commit()
    finally:
        db.close()

ALLOWED_TYPES = {"application/pdf", "text/plain"}


def _sanitize_filename(name: str | None) -> str:
    value = (name or "untitled").replace("\\", "/")
    value = value.rsplit("/", 1)[-1]
    value = value.replace("\x00", "")
    value = re.sub(r"[\x00-\x1f\x7f]+", "", value)
    value = value.strip(" .")
    return value or "untitled"


def _extract_text(file: UploadFile, raw: bytes) -> str:
    if raw.startswith(b"%PDF-"):
        reader = PdfReader(io.BytesIO(raw))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return re.sub(r"[\u200B-\u200D\u2060\uFEFF]", "", text)[: settings.max_document_chars]
    text = raw.decode("utf-8", errors="replace")
    return re.sub(r"[\u200B-\u200D\u2060\uFEFF]", "", text)[: settings.max_document_chars]


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
    if raw.startswith(b"%PDF-"):
        detected_type = "application/pdf"
    else:
        try:
            raw.decode("utf-8")
            detected_type = "text/plain"
        except UnicodeDecodeError:
            detected_type = "binary"

    if detected_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="Only PDF and plain text files are supported")

    safe_name = _sanitize_filename(file.filename)
    doc = Document(org_id=user.org_id, uploaded_by=user.id, filename=safe_name)
    db.add(doc)
    db.flush()
    audit.record(
        db, org_id=user.org_id, actor_id=user.id, action="document.uploaded",
        target_type="document", target_id=doc.id, details={"filename": safe_name},
    )
    db.commit()
    db.refresh(doc)

    try:
        text = _extract_text(file, raw)
        background_tasks.add_task(_process_document_background, doc.id, user.org_id, doc.filename, text)
    except Exception:
        doc.status = "failed"
        db.commit()
        raise HTTPException(status_code=500, detail="Failed to process document")

    return doc


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document_status(doc_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if doc is None or doc.org_id != user.org_id:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("", response_model=list[DocumentOut])
def list_documents(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # org_id comes from the authenticated user, never from the request
    return db.scalars(
        select(Document).where(Document.org_id == user.org_id).order_by(Document.created_at.desc())
    ).all()


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if doc is None or doc.org_id != user.org_id:
        # 404 either way — don't reveal that the doc exists in another org
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.uploaded_by != user.id and role_rank(user.role) < role_rank("ADMIN"):
        raise HTTPException(status_code=403, detail="Only the uploader or an admin can remove this document.")

    delete_document_chunks(doc.id, user.org_id)
    audit.record(
        db, org_id=user.org_id, actor_id=user.id, action="document.deleted",
        target_type="document", target_id=doc.id, details={"filename": doc.filename},
    )
    db.delete(doc)
    db.commit()
