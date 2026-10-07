"""RAG pipeline: chunk -> embed -> store -> retrieve.

Vectors live in the main database (pgvector on Postgres), next to the
documents they belong to. Before this they lived in ChromaDB on Render's
temporary disk, so every restart silently emptied the index while the
documents table still said "ready".

Org isolation (security concern #3) is enforced HERE: every chunk row
carries org_id, and every query filters on it in SQL.
"""
import math
import re

from fastembed import TextEmbedding
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.models import Document, DocumentChunk

settings = get_settings()

_embedder: TextEmbedding | None = None


def get_embedder() -> TextEmbedding:
    global _embedder
    if _embedder is None:
        _embedder = TextEmbedding(model_name=settings.embedding_model)
    return _embedder


def embed_texts(texts: list[str]) -> list[list[float]]:
    return [[float(x) for x in v] for v in get_embedder().embed(texts)]


def _sanitize_extracted_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[\u200B-\u200D\u2060\uFEFF]", "", text)
    text = "".join(ch for ch in text if ch.isprintable() or ch in "\n\r\t")
    return text


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _split_sentences(paragraph: str) -> list[str]:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", paragraph) if s.strip()]
    if not sentences and paragraph.strip():
        return [paragraph.strip()]
    return sentences


def _chunk_long_sentence(sentence: str, max_size: int) -> list[str]:
    return [sentence[i : i + max_size].strip() for i in range(0, len(sentence), max_size)]


def chunk_text(text: str, target_size: int = 800, overlap_sentences: int = 2) -> list[str]:
    """Chunk text on paragraph and sentence boundaries with controlled overlap."""
    text = _sanitize_extracted_text(text)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    def flush_chunk():
        nonlocal current, current_len
        if current:
            chunks.append(" ".join(current).strip())
            current = current[-overlap_sentences:] if overlap_sentences else []
            current_len = sum(len(s) + 1 for s in current)

    for paragraph in _split_paragraphs(text):
        sentences = _split_sentences(paragraph)
        for sentence in sentences:
            if len(sentence) > target_size:
                if current:
                    flush_chunk()
                for part in _chunk_long_sentence(sentence, target_size):
                    chunks.append(part)
                continue

            if current_len + len(sentence) + 1 > target_size and current:
                flush_chunk()

            current.append(sentence)
            current_len += len(sentence) + 1

    if current:
        chunks.append(" ".join(current).strip())
    return chunks


def store_chunks(db: Session, doc_id: str, org_id: str, chunks: list[str], embeddings: list[list[float]]) -> int:
    """Replace a document's chunks. Idempotent, so a retried job never duplicates rows."""
    db.execute(delete(DocumentChunk).where(DocumentChunk.doc_id == doc_id))
    db.add_all(
        DocumentChunk(doc_id=doc_id, org_id=org_id, chunk_index=i, text=chunk, embedding=vector)
        for i, (chunk, vector) in enumerate(zip(chunks, embeddings))
    )
    return len(chunks)


def _cosine_distance(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return 1.0 - (dot / norm if norm else 0.0)


def _retrieve_pg(db: Session, org_id: str, query_vector: list[float], top_k: int,
                 doc_ids: list[str] | None = None) -> list[dict]:
    # Exact search filtered by org_id (btree index), not an ANN index: an HNSW
    # scan followed by an org filter can return fewer than top_k rows for small
    # orgs. Exact search is correct and fast at this scale (< ~100k chunks/org).
    literal = "[" + ",".join(f"{x:.7g}" for x in query_vector) + "]"
    rows = db.execute(
        text(
            """
            SELECT c.text, d.filename, c.chunk_index, c.doc_id, c.embedding <=> CAST(:q AS vector) AS distance
            FROM document_chunks c
            JOIN documents d ON d.id = c.doc_id
            WHERE c.org_id = :org_id AND d.org_id = :org_id AND d.status = 'ready'
            {doc_filter}
            ORDER BY distance
            LIMIT :k
            """.replace("{doc_filter}", "AND c.doc_id = ANY(:doc_ids)" if doc_ids else "")
        ),
        {"q": literal, "org_id": org_id, "k": top_k, **({"doc_ids": list(doc_ids)} if doc_ids else {})},
    ).all()
    return [
        {"text": r.text, "filename": r.filename, "chunk_index": r.chunk_index, "distance": float(r.distance),
         "doc_id": r.doc_id}
        for r in rows
    ]


def _retrieve_python(db: Session, org_id: str, query_vector: list[float], top_k: int,
                     doc_ids: list[str] | None = None) -> list[dict]:
    """Fallback for SQLite (local dev and tests): same filter, cosine in Python."""
    query = (
        select(DocumentChunk.text, DocumentChunk.chunk_index, DocumentChunk.embedding, DocumentChunk.doc_id,
               Document.filename)
        .join(Document, Document.id == DocumentChunk.doc_id)
        .where(DocumentChunk.org_id == org_id, Document.org_id == org_id, Document.status == "ready")
    )
    if doc_ids:
        query = query.where(DocumentChunk.doc_id.in_(doc_ids))
    rows = db.execute(query).all()
    scored = sorted(
        (
            {"text": r.text, "filename": r.filename, "chunk_index": r.chunk_index, "doc_id": r.doc_id,
             "distance": _cosine_distance(query_vector, r.embedding)}
            for r in rows
        ),
        key=lambda item: item["distance"],
    )
    return scored[:top_k]


def retrieve_chunks(org_id: str, query: str, top_k: int | None = None, db: Session | None = None,
                    doc_ids: list[str] | None = None) -> list[dict]:
    """Retrieve top-k chunks for a query, HARD-FILTERED to the caller's org."""
    top_k = top_k if top_k is not None else settings.retrieval_top_k
    query_vector = embed_texts([query])[0]
    own_session = db is None
    db = db or SessionLocal()
    try:
        if db.get_bind().dialect.name == "postgresql":
            return _retrieve_pg(db, org_id, query_vector, top_k, doc_ids)
        return _retrieve_python(db, org_id, query_vector, top_k, doc_ids)
    finally:
        if own_session:
            db.close()
