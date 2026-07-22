"""Document routes: upload (PDF or txt), list, delete — all org-scoped."""
import io

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal, get_db
from app.core.security import get_current_user
from app.models.models import Document, User
from app.models.schemas import DocumentOut
from app.services.rag import delete_document_chunks, ingest_document

router = APIRouter(prefix="/documents", tags=["documents"])
settings = get_settings()


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
        doc = db.get(Document, doc_id)
        if doc is not None:
            doc.status = "failed"
            db.commit()
    finally:
        db.close()

ALLOWED_TYPES = {"application/pdf", "text/plain"}


def _extract_text(file: UploadFile, raw: bytes) -> str:
    if file.content_type == "application/pdf":
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return raw.decode("utf-8", errors="replace")


@router.post("", response_model=DocumentOut, status_code=201)
def upload_document(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="Only PDF and plain text files are supported")

    raw = file.file.read()
    if len(raw) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.max_upload_mb} MB limit")

    doc = Document(org_id=user.org_id, uploaded_by=user.id, filename=file.filename or "untitled")
    db.add(doc)
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

    delete_document_chunks(doc.id, user.org_id)
    db.delete(doc)
    db.commit()
