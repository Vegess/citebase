"""Workspace insights (admins) and suggested starter questions (everyone).

Insights show what people ask, what the documents could not answer
("knowledge gaps": what to upload next), which documents carry the load, and
answers people marked unhelpful. Questions are shown without who asked them.
"""
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models.models import ConversationMessage, Document, User
from app.models.schemas import Suggestion

router = APIRouter(tags=["insights"])

GAP_KINDS = {"abstained", "no_sources"}
_NORMALISE = re.compile(r"[^a-z0-9 ]+")


_MARKDOWN = re.compile(r"[|*_#`>]+|-{3,}")


def _plain_snippet(markdown: str, limit: int = 280) -> str:
    """Answer text without Markdown table pipes, emphasis or headings."""
    return " ".join(_MARKDOWN.sub(" ", markdown).split())[:limit]


def _normalise(question: str) -> str:
    return " ".join(_NORMALISE.sub(" ", question.lower()).split())


@router.get("/documents/suggestions", response_model=list[Suggestion])
def suggested_questions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Up to 6 starter questions from the most recently added ready documents."""
    docs = db.scalars(
        select(Document)
        .where(Document.org_id == user.org_id, Document.status == "ready", Document.suggested_questions.is_not(None))
        .order_by(Document.created_at.desc())
        .limit(6)
    ).all()
    out: list[Suggestion] = []
    for round_ in range(3):  # round-robin so one document doesn't fill every card
        for doc in docs:
            questions = json.loads(doc.suggested_questions or "[]")
            if round_ < len(questions) and len(out) < 6:
                out.append(Suggestion(question=questions[round_], filename=doc.filename, doc_id=doc.id))
    return out


def _paired_turns(db: Session, org_id: str, since: datetime) -> list[tuple[str, ConversationMessage]]:
    """(question, assistant message) pairs in the window, oldest first."""
    rows = db.scalars(
        select(ConversationMessage)
        .where(ConversationMessage.org_id == org_id, ConversationMessage.created_at >= since)
        .order_by(ConversationMessage.conversation_id, ConversationMessage.created_at, ConversationMessage.id)
    ).all()
    pairs: list[tuple[str, ConversationMessage]] = []
    last_question: dict[str, str] = {}
    for msg in rows:
        if msg.role == "user":
            last_question[msg.conversation_id] = msg.content
        elif msg.role == "assistant" and msg.conversation_id in last_question:
            pairs.append((last_question.pop(msg.conversation_id), msg))
    # Across conversations, oldest first: "first phrasing wins" is then stable.
    pairs.sort(key=lambda pair: (pair[1].created_at, pair[1].id))
    return pairs


@router.get("/insights")
def workspace_insights(days: int = 30, user: User = Depends(require_role("ADMIN")),
                       db: Session = Depends(get_db)):
    days = max(1, min(days, 90))
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    pairs = _paired_turns(db, user.org_id, since)
    answers = [msg for _, msg in pairs]

    kinds = Counter(msg.answer_kind or "answered" for msg in answers)
    feedback = Counter(msg.feedback for msg in answers if msg.feedback)

    top = Counter(_normalise(q) for q, _ in pairs)
    display = {}
    for question, _ in pairs:
        display.setdefault(_normalise(question), question.strip())
    top_questions = [{"question": display[key], "count": n} for key, n in top.most_common(8)]

    gaps: dict[str, dict] = {}
    for question, msg in pairs:
        if (msg.answer_kind or "") in GAP_KINDS:
            key = _normalise(question)
            entry = gaps.setdefault(key, {"question": question.strip(), "count": 0, "last_asked": msg.created_at})
            entry["count"] += 1
            entry["last_asked"] = max(entry["last_asked"], msg.created_at)
    knowledge_gaps = sorted(gaps.values(), key=lambda g: (-g["count"], g["question"]))[:10]

    cited = Counter()
    for msg in answers:
        for filename in {c["filename"] for c in json.loads(msg.citations or "[]")}:
            cited[filename] += 1
    top_documents = [{"filename": name, "answers": n} for name, n in cited.most_common(8)]

    unhelpful = [
        {"question": q.strip(), "answer": _plain_snippet(msg.content), "created_at": msg.created_at}
        for q, msg in reversed(pairs) if msg.feedback == -1
    ][:10]

    per_day = Counter(_utc(msg.created_at).date().isoformat() for msg in answers)
    daily = [
        {"date": (now - timedelta(days=offset)).date().isoformat(),
         "questions": per_day.get((now - timedelta(days=offset)).date().isoformat(), 0)}
        for offset in range(min(days, 14) - 1, -1, -1)
    ]

    documents_ready = db.scalar(
        select(func.count()).select_from(Document).where(Document.org_id == user.org_id, Document.status == "ready")
    ) or 0

    total = len(answers)
    return {
        "days": days,
        "totals": {
            "questions": total,
            "answered": kinds.get("answered", 0),
            "not_in_documents": kinds.get("abstained", 0) + kinds.get("no_sources", 0),
            "degraded": kinds.get("fallback", 0),
            "helpful": feedback.get(1, 0),
            "not_helpful": feedback.get(-1, 0),
            "answer_rate": round(kinds.get("answered", 0) / total, 3) if total else None,
            "documents_ready": documents_ready,
        },
        "daily": daily,
        "top_questions": top_questions,
        "knowledge_gaps": knowledge_gaps,
        "top_documents": top_documents,
        "unhelpful_answers": unhelpful,
    }


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@router.get("/home")
def home(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """What a person sees first: recent documents, what needs attention, and
    a setup checklist for new workspaces. Other people's questions are shown
    to admins only, since a question can be personal."""
    from app.core.security import role_rank
    from app.models.models import Conversation, OrgInvite

    is_admin = role_rank(user.role) >= role_rank("ADMIN")
    docs = db.scalars(
        select(Document).where(Document.org_id == user.org_id).order_by(Document.created_at.desc())
    ).all()
    recent = [
        {"id": d.id, "filename": d.filename, "status": d.status, "created_at": d.created_at,
         "summary": _plain_snippet(d.summary or "", 160) if d.summary else None}
        for d in docs[:5]
    ]
    conflicts = [d.filename for d in docs if d.conflicts and json.loads(d.conflicts or "[]")]
    failed = [d.filename for d in docs if d.status in ("failed", "reupload_required")]
    processing = sum(1 for d in docs if d.status in ("queued", "chunking", "embedding"))

    asked = db.scalar(select(func.count()).select_from(Conversation).where(Conversation.user_id == user.id)) or 0
    members = db.scalar(select(func.count()).select_from(User).where(User.org_id == user.org_id, User.is_active)) or 0
    invites = db.scalar(select(func.count()).select_from(OrgInvite).where(
        OrgInvite.org_id == user.org_id, OrgInvite.accepted_at.is_(None), OrgInvite.revoked_at.is_(None))) or 0

    popular, gaps = [], 0
    if is_admin:
        pairs = _paired_turns(db, user.org_id, datetime.now(timezone.utc) - timedelta(days=7))
        counts = Counter(_normalise(q) for q, _ in pairs)
        shown = {}
        for q, _ in pairs:
            shown.setdefault(_normalise(q), q.strip())
        popular = [{"question": shown[k], "count": n} for k, n in counts.most_common(5)]
        gaps = len({_normalise(q) for q, m in pairs if (m.answer_kind or "") in GAP_KINDS})

    return {
        "is_admin": is_admin,
        "documents_total": len(docs),
        "documents_ready": sum(1 for d in docs if d.status == "ready"),
        "processing": processing,
        "recent_documents": recent,
        "popular_questions": popular,
        "alerts": {"conflicts": conflicts, "failed": failed, "unanswered_questions": gaps},
        "checklist": {"has_documents": bool(docs), "has_asked": asked > 0, "has_teammates": members > 1 or invites > 0},
    }
