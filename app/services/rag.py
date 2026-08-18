"""RAG pipeline: chunk -> embed -> store -> retrieve.

Org isolation (security concern #3) is enforced HERE: every chunk is stored
with org_id metadata, and every query filters on it. A user can never
retrieve another org's chunks even if they craft a malicious request.
"""
import re

import chromadb
from chromadb.api import ClientAPI
from sentence_transformers import SentenceTransformer

from app.core.config import get_settings

settings = get_settings()

_embedder: SentenceTransformer | None = None
_chroma: ClientAPI | None = None


def get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(settings.embedding_model)
    return _embedder


def get_collection():
    global _chroma
    if _chroma is None:
        _chroma = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    return _chroma.get_or_create_collection(
        name="documind_chunks",
        metadata={"hnsw:space": "cosine"},
    )


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


def ingest_document(doc_id: str, org_id: str, filename: str, text: str) -> int:
    """Chunk, embed, and store a document. Returns number of chunks."""
    text = _sanitize_extracted_text(text)[: settings.max_document_chars]
    chunks = chunk_text(text)
    if not chunks:
        return 0

    embedder = get_embedder()
    embeddings = embedder.encode(chunks, show_progress_bar=False).tolist()

    collection = get_collection()
    collection.add(
        ids=[f"{doc_id}:{i}" for i in range(len(chunks))],
        embeddings=embeddings,
        documents=chunks,
        metadatas=[
            {"org_id": org_id, "doc_id": doc_id, "filename": filename, "chunk_index": i}
            for i in range(len(chunks))
        ],
    )
    return len(chunks)


def retrieve_chunks(org_id: str, query: str, top_k: int = 5) -> list[dict]:
    """Retrieve top-k chunks for a query, HARD-FILTERED to the caller's org."""
    embedder = get_embedder()
    query_embedding = embedder.encode([query], show_progress_bar=False).tolist()

    collection = get_collection()
    results = collection.query(
        query_embeddings=query_embedding,
        n_results=top_k,
        where={"org_id": org_id},  # org isolation — non-negotiable
    )

    chunks = []
    if results["documents"] and results["documents"][0]:
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            chunks.append({
                "text": doc,
                "filename": meta["filename"],
                "chunk_index": meta["chunk_index"],
                "distance": dist,
            })
    return chunks


def delete_document_chunks(doc_id: str, org_id: str) -> None:
    """Remove all chunks for a document (scoped to org for safety)."""
    collection = get_collection()
    collection.delete(where={"$and": [{"doc_id": doc_id}, {"org_id": org_id}]})
