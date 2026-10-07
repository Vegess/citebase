"""Automatic document summary + suggested questions, run as a job after ingest.

Only queued when an LLM key is configured. A degraded fallback reply is
treated as a failure (the job retries) — a summary must never be the
"closest matching passage" pretending to be a summary.
"""
import json
import logging
import re

from sqlalchemy.orm import Session

from app.models.models import Document
from app.services import jobs
from app.services.answer_plan import _whole_document_chunks
from app.services.generation import GroqRateLimitExceeded, generate_answer, is_fallback

logger = logging.getLogger("app.services.summaries")

KIND = "summarize_document"
BUDGET_CHARS = 8_000

INSTRUCTION = (
    "Read this document and reply with ONLY a JSON object, no other text:\n"
    '{"summary": "<2-3 plain sentences saying what the document is and what it covers>", '
    '"questions": ["<question 1>", "<question 2>", "<question 3>"]}\n'
    "The questions must be ones an employee would ask that THIS document answers. "
    "Do not include citation markers."
)

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)
_MARKERS = re.compile(r"\s*\[\d{1,2}(?:\s*,\s*\d{1,2})*\]")


def parse_summary(reply: str) -> tuple[str, list[str]]:
    match = _JSON_OBJECT.search(reply or "")
    if not match:
        raise ValueError("Model did not return JSON")
    data = json.loads(match.group(0))
    summary = _MARKERS.sub("", str(data.get("summary", ""))).strip()
    questions = [_MARKERS.sub("", str(q)).strip() for q in data.get("questions", []) if str(q).strip()]
    if not summary or not questions:
        raise ValueError("Summary or questions missing")
    return summary[:1000], [q[:200] for q in questions[:3]]


def _run(db: Session, payload: dict) -> None:
    doc = db.get(Document, payload["doc_id"])
    if doc is None or doc.status != "ready":
        return  # deleted or reprocessing; nothing to summarise
    chunks, complete = _whole_document_chunks(db, doc, "overview summary key points", BUDGET_CHARS)
    note = f'The sources are "{doc.filename}" ({"complete" if complete else "the opening and key passages"}).'
    try:
        reply = generate_answer(INSTRUCTION, chunks, note=note, context_limit=BUDGET_CHARS + 1_000)
    except GroqRateLimitExceeded as exc:
        raise RuntimeError("LLM rate limited; will retry") from exc
    if is_fallback(reply):
        raise RuntimeError("LLM unavailable (fallback answer); will retry")
    summary, questions = parse_summary(reply)
    doc.summary = summary
    doc.suggested_questions = json.dumps(questions)
    db.commit()
    logger.info("Summarised doc_id=%s questions=%s", doc.id, len(questions))


jobs.register(KIND, jobs.Handler(run=_run))
