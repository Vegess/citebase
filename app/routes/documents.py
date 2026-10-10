"""Document routes: upload (PDF or txt), list, status, history, delete — all org-scoped.

Upload extracts text immediately (so an unreadable file is rejected while the
user is still looking), then queues the slow part — chunking and embedding —
as a durable job. Status moves through app/services/lifecycle.py.
"""
import io
import logging
import os
import re

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from slowapi.util import get_remote_address
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_user, require_role, role_rank
from app.models.models import Collection, Document, DocumentChunk, DocumentEvent, User
from app.models.schemas import DocumentEventOut, DocumentOut
from app.routes.chat import _user_ip_key, limiter
from app.services import access, audit, conflicts, extract, ingestion, jobs, lifecycle

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
@limiter.limit("20/minute", key_func=_user_ip_key)
def upload_document(
    request: Request,
    file: UploadFile,
    background_tasks: BackgroundTasks,
    collection_id: str | None = Form(default=None),
    user: User = Depends(require_role("MEMBER")),
    db: Session = Depends(get_db),
):
    collection_id = collection_id or None
    if not access.can_use_collection(db, user, collection_id):
        raise HTTPException(status_code=404, detail="Collection not found")
    text, truncated = _read_upload(file)
    return _create_document(db, user, _sanitize_filename(file.filename), text, truncated, background_tasks,
                            collection_id=collection_id)


def _read_upload(file: UploadFile) -> tuple[str, bool]:
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
    return (text[: settings.max_document_chars] if truncated else text), truncated


def _create_document(db: Session, user: User, safe_name: str, text: str, truncated: bool,
                     background_tasks: BackgroundTasks, *, collection_id: str | None = None,
                     previous: Document | None = None) -> Document:
    doc = Document(
        org_id=user.org_id,
        uploaded_by=user.id,
        filename=safe_name,
        status=lifecycle.QUEUED,
        char_count=len(text),
        truncated=truncated,
        collection_id=previous.collection_id if previous else collection_id,
        version=(previous.version + 1) if previous else 1,
        previous_version_id=previous.id if previous else None,
    )
    db.add(doc)
    db.flush()
    lifecycle.record_created(db, doc, detail="truncated" if truncated else None)
    jobs.enqueue(db, ingestion.KIND, {"doc_id": doc.id, "org_id": user.org_id, "text": text})
    audit.record(
        db, org_id=user.org_id, actor_id=user.id, action="document.uploaded",
        target_type="document", target_id=doc.id,
        details={"filename": safe_name, "truncated": truncated, **({"version": doc.version} if previous else {})},
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
    query = select(Document).where(Document.org_id == user.org_id).where(
        access.document_filter(access.scope_for(db, user).collections))
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
    if not access.can_see(access.scope_for(db, user), doc):
        # 404 either way: don't reveal that it exists in another workspace or a restricted collection
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def _can_manage(user: User, doc: Document) -> bool:
    return doc.uploaded_by == user.id or role_rank(user.role) >= role_rank("ADMIN")


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
def list_documents(include_superseded: bool = False, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    # org_id comes from the authenticated user, never from the request
    query = (select(Document).where(Document.org_id == user.org_id)
             .where(access.document_filter(access.scope_for(db, user).collections))
             .order_by(Document.created_at.desc()))
    if not include_superseded:
        query = query.where(Document.status != lifecycle.SUPERSEDED)
    return db.scalars(query).all()


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doc = db.scalar(
        select(Document).where(Document.id == doc_id, Document.org_id == user.org_id).with_for_update()
    )
    if not access.can_see(access.scope_for(db, user), doc):
        raise HTTPException(status_code=404, detail="Document not found")
    if not _can_manage(user, doc):
        raise HTTPException(status_code=403, detail="Only the uploader or an admin can remove this document.")
    if doc.previous_version_id and doc.status != lifecycle.SUPERSEDED:
        # Removing the current version brings the previous one back.
        previous = db.get(Document, doc.previous_version_id)
        if previous is not None and previous.status == lifecycle.SUPERSEDED:
            lifecycle.transition(db, previous.id, lifecycle.READY, detail=f"version {doc.version} was removed")

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



# ---- Versions, collections, conflicts, detail ----

@router.post("/{doc_id}/versions", response_model=DocumentOut, status_code=201)
def upload_new_version(doc_id: str, file: UploadFile, background_tasks: BackgroundTasks,
                       user: User = Depends(require_role("MEMBER")), db: Session = Depends(get_db)):
    """Replace a document with a newer file. The current version keeps
    answering until the new one is ready, then it is marked superseded."""
    current = _own_doc_or_404(db, doc_id, user)
    if not _can_manage(user, current):
        raise HTTPException(status_code=403, detail="Only the uploader or an admin can upload a new version.")
    text, truncated = _read_upload(file)
    # Lock the current version so two uploads at once can't both become "next".
    current = db.scalar(select(Document).where(Document.id == current.id).with_for_update())
    if current.status == lifecycle.SUPERSEDED:
        raise HTTPException(status_code=409, detail="This is an older version. Upload to the current one.")
    if db.scalar(select(Document.id).where(Document.previous_version_id == current.id)) is not None:
        raise HTTPException(status_code=409, detail="A newer version is already being processed. Open it instead.")
    return _create_document(db, user, _sanitize_filename(file.filename), text, truncated, background_tasks,
                            previous=current)


class MoveDocument(BaseModel):
    collection_id: str | None = None


def _version_chain(db: Session, doc: Document) -> list[Document]:
    """Every version of this document, oldest first."""
    chain = [doc]
    seen = {doc.id}
    cursor = doc
    while cursor.previous_version_id and cursor.previous_version_id not in seen:
        cursor = db.get(Document, cursor.previous_version_id)
        if cursor is None or cursor.org_id != doc.org_id:
            break
        chain.insert(0, cursor)
        seen.add(cursor.id)
    cursor = doc
    while True:
        newer = db.scalar(select(Document).where(Document.previous_version_id == cursor.id,
                                                 Document.org_id == doc.org_id))
        if newer is None or newer.id in seen:
            break
        chain.append(newer)
        seen.add(newer.id)
        cursor = newer
    return chain


@router.patch("/{doc_id}", response_model=DocumentOut)
def move_document(doc_id: str, body: MoveDocument, user: User = Depends(require_role("MEMBER")),
                  db: Session = Depends(get_db)):
    doc = _own_doc_or_404(db, doc_id, user)
    if not _can_manage(user, doc):
        raise HTTPException(status_code=403, detail="Only the uploader or an admin can move this document.")
    target = body.collection_id or None
    if not access.can_use_collection(db, user, target):
        raise HTTPException(status_code=404, detail="Collection not found")
    chain = _version_chain(db, doc)
    for version in chain:  # versions move together
        version.collection_id = target
    # Warnings on these files quote other files, and other files' warnings may
    # quote these: both were computed for the old audience, so check again.
    names = {v.filename for v in chain}
    conflicts.recheck(db, chain + [d for d in conflicts.mentioning(db, user.org_id, names) if d not in chain])
    audit.record(db, org_id=user.org_id, actor_id=user.id, action="document.moved", target_type="document",
                 target_id=doc.id, details={"filename": doc.filename, "collection_id": target})
    db.commit()
    db.refresh(doc)
    return doc


class ConflictReview(BaseModel):
    state: str | None  # resolved | ignored | None (reopen)


@router.post("/{doc_id}/conflicts", response_model=DocumentOut)
def review_conflicts(doc_id: str, body: ConflictReview, user: User = Depends(require_role("ADMIN")),
                     db: Session = Depends(get_db)):
    if body.state not in ("resolved", "ignored", None):
        raise HTTPException(status_code=400, detail="state must be resolved, ignored or null")
    doc = _own_doc_or_404(db, doc_id, user)
    doc.conflicts_state = body.state
    audit.record(db, org_id=user.org_id, actor_id=user.id, action="document.conflicts_reviewed",
                 target_type="document", target_id=doc.id, details={"filename": doc.filename, "state": body.state})
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/{doc_id}/detail")
def document_detail(doc_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doc = _own_doc_or_404(db, doc_id, user)
    uploader = db.get(User, doc.uploaded_by)
    collection = db.get(Collection, doc.collection_id) if doc.collection_id else None
    events = db.scalars(select(DocumentEvent).where(DocumentEvent.doc_id == doc.id).order_by(DocumentEvent.id)).all()
    versions = _version_chain(db, doc)
    return {
        "document": DocumentOut.model_validate(doc).model_dump(),
        "uploaded_by_email": uploader.email if uploader else None,
        "collection": {"id": collection.id, "name": collection.name, "restricted": collection.restricted}
        if collection else None,
        "can_manage": _can_manage(user, doc),
        "events": [DocumentEventOut.model_validate(e).model_dump() for e in events],
        "versions": [
            {"id": v.id, "version": v.version, "filename": v.filename, "status": v.status, "created_at": v.created_at,
             "uploaded_by_email": (db.get(User, v.uploaded_by).email if db.get(User, v.uploaded_by) else None)}
            for v in versions
        ],
    }
