"""Verified answers: an admin approves an answer once; the same question then
gets it instantly, with no model call, marked as verified.

A verified answer is only served while every document it cites is still
current (not deleted, not replaced by a newer version) and visible to the
person asking, so it can't go stale silently or leak a restricted document.
"""
import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Document, User, VerifiedAnswer
from app.services import access

_NORMALISE = re.compile(r"[^a-z0-9 ]+")


def question_key(question: str) -> str:
    return " ".join(_NORMALISE.sub(" ", question.lower()).split())[:300]


def usable(db: Session, scope: access.Scope, answer: VerifiedAnswer) -> bool:
    citations = json.loads(answer.citations or "[]")
    doc_ids = {c.get("doc_id") for c in citations}
    if not citations or None in doc_ids:
        return False
    docs = {d.id: d for d in db.scalars(select(Document).where(Document.id.in_(doc_ids)))}
    return all(
        (doc := docs.get(doc_id)) is not None and doc.status == "ready" and access.can_see(scope, doc)
        for doc_id in doc_ids
    )


def find(db: Session, scope: access.Scope, question: str) -> VerifiedAnswer | None:
    key = question_key(question)
    if not key:
        return None
    answer = db.scalar(select(VerifiedAnswer).where(
        VerifiedAnswer.org_id == scope.org_id, VerifiedAnswer.question_key == key))
    return answer if answer is not None and usable(db, scope, answer) else None


def describe(db: Session, answer: VerifiedAnswer) -> dict:
    by = db.get(User, answer.verified_by) if answer.verified_by else None
    return {"by": by.email if by else None, "at": answer.created_at.isoformat() if answer.created_at else None}
