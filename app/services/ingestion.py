"""Document ingestion as a queued job: chunk -> embed -> store, with every
step recorded through the lifecycle state machine."""
import logging

from sqlalchemy.orm import Session

from app.models.models import Document
from app.services import jobs, lifecycle
from app.services.generation import llm_configured
from app.services.rag import chunk_document, embed_texts, store_chunks

SUMMARY_KIND = "summarize_document"  # handler lives in app/services/summaries.py

logger = logging.getLogger("app.services.ingestion")

KIND = "ingest_document"
EMBED_BATCH = 64


def _run(db: Session, payload: dict) -> None:
    doc_id, org_id = payload["doc_id"], payload["org_id"]

    if lifecycle.transition(db, doc_id, lifecycle.CHUNKING) is None:
        return  # deleted before we started
    db.commit()

    chunks = chunk_document(payload["text"])
    if not chunks:
        lifecycle.transition(db, doc_id, lifecycle.FAILED, detail="no text after cleaning",
                             error="No readable text was found in this file.")
        db.commit()
        return

    if lifecycle.transition(db, doc_id, lifecycle.EMBEDDING, detail=f"{len(chunks)} passage{'' if len(chunks) == 1 else 's'}") is None:
        return
    db.commit()

    vectors: list[list[float]] = []
    for start in range(0, len(chunks), EMBED_BATCH):
        vectors.extend(embed_texts(chunks[start:start + EMBED_BATCH]))

    # Chunks and the READY status commit together: a document is never "ready"
    # without its vectors, and never has vectors while still "embedding".
    store_chunks(db, doc_id, org_id, chunks, vectors)
    doc = lifecycle.transition(db, doc_id, lifecycle.READY, num_chunks=len(chunks), error=None)
    if doc is None:
        db.rollback()
        return
    if doc.previous_version_id:
        # The new version is searchable now; retire the old one in the same commit,
        # so there is never a moment with neither or both versions answering.
        previous = db.get(Document, doc.previous_version_id)
        if previous is not None and previous.status == lifecycle.READY:
            lifecycle.transition(db, previous.id, lifecycle.SUPERSEDED, detail=f"replaced by version {doc.version}")
    if llm_configured():
        # Same transaction as READY: a ready document always gets its summary job.
        jobs.enqueue(db, SUMMARY_KIND, {"doc_id": doc_id})
    db.commit()
    logger.info("Ingested doc_id=%s org_id=%s chunks=%s", doc_id, org_id, len(chunks))


def _on_error(db: Session, payload: dict, exc: Exception, final: bool) -> None:
    target = lifecycle.FAILED if final else lifecycle.QUEUED
    message = (
        "Processing failed. Try uploading the file again."
        if final else "Temporary problem while processing; retrying automatically."
    )
    # Users see document history, so it gets a plain description; the exception
    # itself (which can contain database or provider details) stays in the logs.
    logger.warning("Ingest failed doc_id=%s final=%s: %s: %s", payload.get("doc_id"), final,
                   type(exc).__name__, str(exc)[:300])
    detail = "gave up after retries" if final else "will retry"
    try:
        lifecycle.transition(db, payload["doc_id"], target, detail=detail, error=message)
    except lifecycle.InvalidTransition:
        # Failed before leaving `queued` (e.g. DB blip on the first transition).
        if final:
            lifecycle.transition(db, payload["doc_id"], lifecycle.FAILED, detail=detail, error=message)


jobs.register(KIND, jobs.Handler(run=_run, on_error=_on_error, scrub_keys=("text",)))
