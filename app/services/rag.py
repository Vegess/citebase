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
import threading

from fastembed import TextEmbedding
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.models import Document, DocumentChunk
from app.services import access

settings = get_settings()

_embedder: TextEmbedding | None = None
_embedder_lock = threading.Lock()


def get_embedder() -> TextEmbedding:
    """Load the model once. The lock stops the startup warm-up and an early
    request from loading two copies at the same time (memory is tight on the
    free tier)."""
    global _embedder
    if _embedder is None:
        with _embedder_lock:
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


_NUMBERED_HEADING = re.compile(r"^(\d+(\.\d+)*[.)]?|[A-Z][.)]|[IVX]+\.)\s+\S")


def _looks_like_heading(line: str) -> bool:
    """Short standalone lines that title what follows: "3. Probation",
    "## Leave", "TECHNICAL SKILLS", "Education:", "Work Experience"."""
    line = line.strip()
    if not line or len(line) > 70 or line[-1] in ".,;!?" or not re.search(r"[A-Za-z]", line):
        return False
    if line.startswith("#") or line.endswith(":") or _NUMBERED_HEADING.match(line):
        return True
    words = re.findall(r"[A-Za-z][A-Za-z&/'-]*", line)
    if not words or len(words) > 5 or re.search(r"[,\d|]", line):
        return False  # lists, dates and figures are content, not titles
    if line.isupper():
        return True
    significant = [w for w in words if len(w) > 3]
    return bool(significant) and all(w[0].isupper() for w in significant)


def split_sections(text: str) -> list[tuple[str | None, str]]:
    """[(heading, body)] in reading order; text before the first heading has heading None."""
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    lines = text.splitlines()
    for i, raw in enumerate(lines):
        line = raw.strip()
        nxt = next((l.strip() for l in lines[i + 1:] if l.strip()), "")
        if _looks_like_heading(line) and nxt and not _looks_like_heading(nxt):
            sections.append((line.lstrip("#").strip().rstrip(":"), []))
        else:
            sections[-1][1].append(raw)
    return [(h, "\n".join(body).strip()) for h, body in sections if "\n".join(body).strip()]


def chunk_document(text: str, target_size: int = 800, min_section: int = 250) -> list[str]:
    """Heading-aware chunking. Each chunk starts with the heading(s) it sits
    under, so a passage like "30 days' written notice" is retrieved and cited
    together with "4. Notice period". Tiny neighbouring sections are merged so
    a ten-line policy does not become ten one-line chunks. Text with no
    recognisable headings falls back to plain paragraph/sentence chunking."""
    text = _sanitize_extracted_text(text)
    sections = split_sections(text)
    if sum(1 for heading, _ in sections if heading) < 2:
        return chunk_text(text, target_size)

    def render(heading: str | None, body: str) -> str:
        return f"{heading}\n{body}" if heading else body

    # Group tiny neighbouring sections, keeping each heading next to its own text.
    groups: list[list[tuple[str | None, str]]] = []
    for heading, body in sections:
        if groups and sum(len(render(h, b)) for h, b in groups[-1]) < min_section:
            groups[-1].append((heading, body))
        else:
            groups.append([(heading, body)])

    chunks: list[str] = []
    for group in groups:
        combined = "\n\n".join(render(h, b) for h, b in group)
        if len(combined) <= target_size:
            chunks.append(combined)
            continue
        for heading, body in group:
            prefix = f"{heading}\n" if heading else ""
            chunks.extend(prefix + piece for piece in chunk_text(body, target_size - len(prefix)))
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
                 doc_ids: list[str] | None = None, collections: tuple[str, ...] | None = None) -> list[dict]:
    # Exact search filtered by org_id (btree index), not an ANN index: an HNSW
    # scan followed by an org filter can return fewer than top_k rows for small
    # orgs. Exact search is correct and fast at this scale (< ~100k chunks/org).
    literal = "[" + ",".join(f"{x:.7g}" for x in query_vector) + "]"
    scope_sql, scope_params = access.sql_filter(collections)
    rows = db.execute(
        text(
            """
            SELECT c.text, d.filename, c.chunk_index, c.doc_id, c.embedding <=> CAST(:q AS vector) AS distance
            FROM document_chunks c
            JOIN documents d ON d.id = c.doc_id
            WHERE c.org_id = :org_id AND d.org_id = :org_id AND d.status = 'ready'
            {doc_filter} {scope}
            ORDER BY distance
            LIMIT :k
            """.replace("{doc_filter}", "AND c.doc_id = ANY(:doc_ids)" if doc_ids else "").replace("{scope}", scope_sql)
        ),
        {"q": literal, "org_id": org_id, "k": top_k, **({"doc_ids": list(doc_ids)} if doc_ids else {}), **scope_params},
    ).all()
    return [
        {"text": r.text, "filename": r.filename, "chunk_index": r.chunk_index, "distance": float(r.distance),
         "doc_id": r.doc_id}
        for r in rows
    ]


def _retrieve_python(db: Session, org_id: str, query_vector: list[float], top_k: int,
                     doc_ids: list[str] | None = None, collections: tuple[str, ...] | None = None) -> list[dict]:
    """Fallback for SQLite (local dev and tests): same filter, cosine in Python."""
    query = (
        select(DocumentChunk.text, DocumentChunk.chunk_index, DocumentChunk.embedding, DocumentChunk.doc_id,
               Document.filename)
        .join(Document, Document.id == DocumentChunk.doc_id)
        .where(DocumentChunk.org_id == org_id, Document.org_id == org_id, Document.status == "ready")
        .where(access.document_filter(collections))
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


# ---- Keyword search ----
# Embeddings match meaning but blur exact tokens: a policy number, "POSH",
# "127162001", "Rs 6,000". Keyword search catches those; the two lists are
# fused with reciprocal-rank fusion so neither score scale dominates.

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from", "how", "i", "in",
    "is", "it", "its", "me", "my", "of", "on", "or", "our", "the", "their", "there", "this", "to", "we",
    "what", "when", "where", "which", "who", "why", "will", "with", "you", "your", "much", "many", "get",
}
_TOKEN = re.compile(r"[a-z0-9]+")


def _stem(token: str) -> str:
    """Light plural folding so "passwords" matches "password" (Postgres FTS
    stems with its English dictionary; this keeps the SQLite path comparable)."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def keyword_terms(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN.findall(text.lower())
            if t not in _STOPWORDS and (len(t) > 1 or t.isdigit())]


def _keyword_pg(db: Session, org_id: str, query: str, limit: int, doc_ids: list[str] | None,
                collections: tuple[str, ...] | None = None) -> list[dict]:
    terms = sorted(set(keyword_terms(query)))
    if not terms:
        return []
    scope_sql, scope_params = access.sql_filter(collections)
    # Terms are [a-z0-9] only, so this OR-query cannot inject tsquery syntax.
    rows = db.execute(
        text(
            """
            SELECT c.text, d.filename, c.chunk_index, c.doc_id,
                   ts_rank_cd(to_tsvector('english', c.text), to_tsquery('english', :tsq)) AS rank
            FROM document_chunks c
            JOIN documents d ON d.id = c.doc_id
            WHERE c.org_id = :org_id AND d.org_id = :org_id AND d.status = 'ready'
              AND to_tsvector('english', c.text) @@ to_tsquery('english', :tsq)
            {doc_filter} {scope}
            ORDER BY rank DESC
            LIMIT :k
            """.replace("{doc_filter}", "AND c.doc_id = ANY(:doc_ids)" if doc_ids else "").replace("{scope}", scope_sql)
        ),
        {"tsq": " | ".join(terms), "org_id": org_id, "k": limit, **({"doc_ids": list(doc_ids)} if doc_ids else {}),
         **scope_params},
    ).all()
    return [{"text": r.text, "filename": r.filename, "chunk_index": r.chunk_index, "doc_id": r.doc_id} for r in rows]


def _keyword_python(db: Session, org_id: str, query: str, limit: int, doc_ids: list[str] | None,
                    collections: tuple[str, ...] | None = None) -> list[dict]:
    """BM25 over the org's chunks (SQLite / local dev)."""
    terms = set(keyword_terms(query))
    if not terms:
        return []
    q = (
        select(DocumentChunk.text, DocumentChunk.chunk_index, DocumentChunk.doc_id, Document.filename)
        .join(Document, Document.id == DocumentChunk.doc_id)
        .where(DocumentChunk.org_id == org_id, Document.org_id == org_id, Document.status == "ready")
        .where(access.document_filter(collections))
    )
    if doc_ids:
        q = q.where(DocumentChunk.doc_id.in_(doc_ids))
    rows = db.execute(q).all()
    if not rows:
        return []
    docs = [keyword_terms(r.text) for r in rows]
    avg_len = sum(len(d) for d in docs) / len(docs) or 1.0
    df = {t: sum(1 for d in docs if t in d) for t in terms}
    k1, b = 1.5, 0.75
    scored = []
    for r, tokens in zip(rows, docs):
        score = 0.0
        for t in terms:
            tf = tokens.count(t)
            if tf:
                idf = math.log(1 + (len(docs) - df[t] + 0.5) / (df[t] + 0.5))
                score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(tokens) / avg_len))
        if score > 0:
            scored.append((score, r))
    scored.sort(key=lambda item: -item[0])
    return [{"text": r.text, "filename": r.filename, "chunk_index": r.chunk_index, "doc_id": r.doc_id}
            for _, r in scored[:limit]]


def _fuse(vector_hits: list[dict], keyword_hits: list[dict], top_k: int, k: int = 60) -> list[dict]:
    """Reciprocal-rank fusion: score = sum 1/(k + rank) over both lists."""
    scores: dict[tuple, float] = {}
    items: dict[tuple, dict] = {}
    for hits in (vector_hits, keyword_hits):
        for rank, hit in enumerate(hits, start=1):
            key = (hit["doc_id"], hit["chunk_index"])
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            items.setdefault(key, hit)
    ranked = sorted(scores, key=lambda key: -scores[key])[:top_k]
    return [{**items[key], "score": round(scores[key], 5)} for key in ranked]


def retrieve_chunks(org_id: str, query: str, top_k: int | None = None, db: Session | None = None,
                    doc_ids: list[str] | None = None, hybrid: bool | None = None,
                    collections: tuple[str, ...] | None = None) -> list[dict]:
    """Retrieve top-k chunks for a query, HARD-FILTERED to the caller's org and
    to the collections they may see (`collections`, see services/access.py).
    Hybrid (vector + keyword, RRF-fused) unless HYBRID_SEARCH=false."""
    top_k = top_k if top_k is not None else settings.retrieval_top_k
    hybrid = settings.hybrid_search if hybrid is None else hybrid
    query_vector = embed_texts([query])[0]
    own_session = db is None
    db = db or SessionLocal()
    try:
        is_pg = db.get_bind().dialect.name == "postgresql"
        pool = top_k * 4 if hybrid else top_k
        vector_hits = (_retrieve_pg if is_pg else _retrieve_python)(db, org_id, query_vector, pool, doc_ids, collections)
        if not hybrid:
            return vector_hits[:top_k]
        keyword_hits = (_keyword_pg if is_pg else _keyword_python)(db, org_id, query, pool, doc_ids, collections)
        return _fuse(vector_hits, keyword_hits, top_k)
    finally:
        if own_session:
            db.close()
