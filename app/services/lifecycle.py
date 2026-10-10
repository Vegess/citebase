"""Document lifecycle: a strict state machine with a history row per change.

    queued ──> chunking ──> embedding ──> ready
       ^          │             │           │
       └── retry ─┴─────────────┘           │ (reprocess)
       │          v             v           │
       └────── failed <─────────────────────┘ ... ready -> queued

`superseded`: a newer version of the file became ready. The old one stays for
the history (and old citations) but is no longer searched; deleting the newer
version brings it back to `ready`.

`reupload_required` is set only by migration 0005 for documents whose vectors
were lost with the old ChromaDB disk; it has no way out except deletion.

Every transition locks the document row (SELECT ... FOR UPDATE), checks the
move is allowed, updates it and appends a document_events row, all inside the
caller's transaction. An illegal move raises InvalidTransition instead of
silently writing a status that hides what actually happened.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Document, DocumentEvent

QUEUED, CHUNKING, EMBEDDING, READY, FAILED, REUPLOAD, SUPERSEDED = (
    "queued", "chunking", "embedding", "ready", "failed", "reupload_required", "superseded",
)

ALLOWED: dict[str, set[str]] = {
    QUEUED: {CHUNKING, FAILED},
    CHUNKING: {EMBEDDING, FAILED, QUEUED},   # QUEUED = retry after a transient error
    EMBEDDING: {READY, FAILED, QUEUED},
    READY: {QUEUED, SUPERSEDED},             # reprocess; replaced by a newer version
    SUPERSEDED: {READY},                     # the newer version was deleted
    FAILED: {QUEUED},                        # manual retry
    REUPLOAD: set(),
}
IN_PROGRESS = {QUEUED, CHUNKING, EMBEDDING}


class InvalidTransition(Exception):
    def __init__(self, doc_id: str, current: str, target: str):
        super().__init__(f"Document {doc_id}: cannot move from {current!r} to {target!r}")
        self.current = current
        self.target = target


def record_created(db: Session, doc: Document, detail: str | None = None) -> None:
    db.add(DocumentEvent(doc_id=doc.id, org_id=doc.org_id, from_status=None, to_status=doc.status, detail=detail))


def transition(db: Session, doc_id: str, target: str, *, detail: str | None = None, **fields) -> Document | None:
    """Move a document to `target`. Returns None if the document no longer exists
    (deleted while its job was running), so callers can stop quietly."""
    doc = db.scalar(select(Document).where(Document.id == doc_id).with_for_update())
    if doc is None:
        return None
    if target not in ALLOWED.get(doc.status, set()):
        raise InvalidTransition(doc_id, doc.status, target)

    db.add(DocumentEvent(doc_id=doc.id, org_id=doc.org_id, from_status=doc.status, to_status=target, detail=detail))
    doc.status = target
    for name, value in fields.items():
        setattr(doc, name, value)
    db.flush()
    return doc
