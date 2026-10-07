"""Decide what the model gets to read before it answers.

Two kinds of request need different context:

* A **question** ("what is the notice period?") is answered from the few most
  relevant passages across the org's documents (top-k retrieval).
* A **document task** ("review and rate my resume", "summarise the travel
  policy", "compare the two contracts") needs the document itself, in order.
  Three disconnected top-k passages are why the live app answered "the
  document hasn't been provided" while citing that very document.

Routing is rule-based on purpose: no extra LLM call (cost, latency and
free-tier rate limits), deterministic, and unit-testable. Target documents are
resolved from file names mentioned in the question, then phrases like "the
file I just uploaded", then "the only document", then the best search hit.
"""
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.models import Document, DocumentChunk
from app.services import rag

settings = get_settings()

_DOC_TASK = re.compile(
    r"\b(summari[sz]e|summary|overview|tl;?dr|key (points|takeaways|findings)"
    r"|review|rate|rating|score|assess|evaluate|critique|proofread|improve|feedback"
    r"|compare|comparison|difference between|differences between"
    r"|(explain|describe|walk me through)( (me|us|to me))? (this|the|my|that|each|both|these)\b[\w\s]{0,30}\b"
    r"(document|file|pdf|resume|cv|report|policy|contract|handbook)s?"
    r"|what('s| is) (this|the|that|my) [\w\s]{0,20}(document|file|pdf|resume|cv|report|policy|contract) about)\b",
    re.IGNORECASE,
)
_LATEST = re.compile(
    r"\b(new|newly|latest|last|recent|recently|just)\b[\w\s]{0,25}\b(upload|uploaded|added|document|file|pdf)",
    re.IGNORECASE,
)
_FOLLOW_UP = re.compile(r"\b(it|its|that|this|those|these|they|them|he|she|his|her|above|same)\b", re.IGNORECASE)
_STOP_TOKENS = {
    "pdf", "txt", "doc", "docx", "document", "file", "final", "copy", "version", "draft",
    "the", "and", "for", "with", "new", "old",
}


@dataclass
class AnswerPlan:
    mode: str  # "question" | "document"
    chunks: list[dict]
    note: str | None = None
    context_limit: int | None = None
    target_docs: list[str] = field(default_factory=list)  # filenames, for logs and tests


def is_document_task(question: str) -> bool:
    return bool(_DOC_TASK.search(question))


def _filename_tokens(filename: str) -> set[str]:
    stem = filename.rsplit(".", 1)[0].lower()
    return {
        token for token in re.split(r"[^a-z0-9]+", stem)
        if token not in _STOP_TOKENS and (len(token) >= 4 or (token.isdigit() and len(token) >= 3))
    }


def match_documents_by_name(question: str, docs: list[Document]) -> list[Document]:
    """Documents whose file-name words appear in the question, best match first.
    Returns every document tied for the best score (used for comparisons)."""
    words = set(re.split(r"[^a-z0-9]+", question.lower()))
    scored = [(len(_filename_tokens(d.filename) & words), d) for d in docs]
    best = max((score for score, _ in scored), default=0)
    if best == 0:
        return []
    return [d for score, d in scored if score == best]


def _ready_documents(db: Session, org_id: str) -> list[Document]:
    return list(
        db.scalars(
            select(Document)
            .where(Document.org_id == org_id, Document.status == "ready")
            .order_by(Document.created_at.desc())
        )
    )


def retrieval_query(question: str, history: list[dict] | None) -> str:
    """Short follow-ups ("and for interns?", "what about its deadline?") carry
    little meaning on their own; borrow the previous question's words."""
    if not history:
        return question
    previous = next((t["content"] for t in reversed(history) if t.get("role") == "user"), None)
    if previous and (len(question.split()) <= 6 or _FOLLOW_UP.search(question)):
        return f"{previous} {question}"
    return question


def _whole_document_chunks(db: Session, doc: Document, question: str, budget: int) -> tuple[list[dict], bool]:
    """All passages of `doc` in reading order if they fit the budget; otherwise
    the opening passages plus the ones most relevant to the question, still in
    reading order. Returns (chunks, complete)."""
    rows = db.execute(
        select(DocumentChunk.chunk_index, DocumentChunk.text)
        .where(DocumentChunk.doc_id == doc.id)
        .order_by(DocumentChunk.chunk_index)
    ).all()
    passages = [{"text": r.text, "filename": doc.filename, "chunk_index": r.chunk_index, "doc_id": doc.id}
                for r in rows]
    if sum(len(p["text"]) for p in passages) <= budget:
        return passages, True

    keep: dict[int, dict] = {}
    used = 0

    def take(passage: dict) -> bool:
        nonlocal used
        if passage["chunk_index"] in keep or used + len(passage["text"]) > budget:
            return False
        keep[passage["chunk_index"]] = passage
        used += len(passage["text"])
        return True

    for passage in passages[:2]:  # the opening usually says what the document is
        take(passage)
    for hit in rag.retrieve_chunks(doc.org_id, question, top_k=len(passages), db=db, doc_ids=[doc.id]):
        take(next(p for p in passages if p["chunk_index"] == hit["chunk_index"]))
    return [keep[i] for i in sorted(keep)], False


def plan_answer(db: Session, org_id: str, question: str, history: list[dict] | None = None) -> AnswerPlan:
    docs = _ready_documents(db, org_id)
    named = match_documents_by_name(question, docs)
    query = retrieval_query(question, history)

    if is_document_task(question) and docs:
        if named:
            targets = named
        elif _LATEST.search(question):
            targets = docs[:1]
        elif len(docs) == 1:
            targets = docs
        else:
            hits = rag.retrieve_chunks(org_id, query, top_k=1, db=db)
            targets = [d for d in docs if hits and d.id == hits[0]["doc_id"]]
        targets = targets[:3]

        if targets:
            budget = settings.whole_doc_chars // len(targets)
            chunks: list[dict] = []
            coverage: list[str] = []
            for doc in targets:
                doc_chunks, complete = _whole_document_chunks(db, doc, question, budget)
                chunks.extend(doc_chunks)
                coverage.append(f'"{doc.filename}" ({"complete" if complete else "selected passages, not the whole file"})')
            note = (
                "The user is asking about whole documents. The sources below are, in reading order: "
                + "; ".join(coverage)
                + ". Treat them as the document itself. Do the task they ask for (summary, review, "
                "rating, comparison) directly from this content, citing passages. If the sources are "
                "only part of a document, say your answer is based on the parts provided."
            )
            return AnswerPlan("document", chunks, note, settings.whole_doc_chars + 2_000,
                              [d.filename for d in targets])

    doc_ids = [d.id for d in named] if named else None
    chunks = rag.retrieve_chunks(org_id, query, top_k=settings.retrieval_top_k, db=db, doc_ids=doc_ids)
    if doc_ids and not chunks:  # the name matched but nothing relevant inside: search everything
        chunks = rag.retrieve_chunks(org_id, query, top_k=settings.retrieval_top_k, db=db)
    return AnswerPlan("question", chunks, None, None, [d.filename for d in named])
