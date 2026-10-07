"""Persistent daily question quotas."""
from datetime import date, datetime, timedelta, timezone
from math import ceil

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.models import QuestionUsage

settings = get_settings()
GLOBAL_SCOPE = "global"


def _today(now: datetime | None = None) -> date:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).date()


def _retry_after(now: datetime | None = None) -> int:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    next_day = (current.astimezone(timezone.utc) + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(1, ceil((next_day - current.astimezone(timezone.utc)).total_seconds()))


def _get_usage(db: Session, usage_date: date, scope: str) -> QuestionUsage:
    usage = db.scalar(
        select(QuestionUsage).where(
            QuestionUsage.usage_date == usage_date,
            QuestionUsage.scope == scope,
        )
    )
    if usage is None:
        usage = QuestionUsage(usage_date=usage_date, scope=scope, question_count=0)
        db.add(usage)
        db.flush()
    return usage


def get_usage(db: Session, now: datetime | None = None) -> int:
    usage = db.scalar(
        select(QuestionUsage.question_count).where(
            QuestionUsage.usage_date == _today(now),
            QuestionUsage.scope == GLOBAL_SCOPE,
        )
    )
    return usage or 0


_LIMIT_MESSAGES = {
    "global": "This demo has reached its daily AI quota. Please try again tomorrow.",
    "org": "Your workspace has reached its daily question limit. Please try again tomorrow.",
    "user": "You've reached your daily question limit for this demo. Please try again tomorrow.",
}


def _scopes(user_id: str, org_id: str | None) -> list[tuple[str, str, int]]:
    """(kind, scope key, cap). User rows keep the bare user id for continuity
    with counters written before org scopes existed."""
    scopes = [("global", GLOBAL_SCOPE, settings.daily_question_cap)]
    if org_id:
        scopes.append(("org", f"org:{org_id}", settings.per_org_daily_cap))
    scopes.append(("user", user_id, settings.per_user_daily_cap))
    return scopes


def _ensure_row(db: Session, usage_date: date, scope: str) -> None:
    exists = db.scalar(
        select(QuestionUsage.id).where(QuestionUsage.usage_date == usage_date, QuestionUsage.scope == scope)
    )
    if exists is not None:
        return
    try:
        with db.begin_nested():
            db.add(QuestionUsage(usage_date=usage_date, scope=scope, question_count=0))
    except IntegrityError:
        pass  # another request created it first; the unique constraint did its job


def reserve_question(db: Session, user_id: str, now: datetime | None = None, *, org_id: str | None = None) -> None:
    """Reserve one question against every applicable cap, or raise HTTP 429.

    Each counter moves with a single conditional UPDATE
    (`SET n = n + 1 WHERE n < cap`), so two concurrent requests can never both
    take the last slot — the old read-check-write could, and could also exceed
    the cap. All counters change together or not at all (one SAVEPOINT).
    """
    current_date = _today(now)
    retry_after = str(_retry_after(now))
    scopes = _scopes(user_id, org_id)
    for _, scope, _ in scopes:
        _ensure_row(db, current_date, scope)

    savepoint = db.begin_nested()
    for kind, scope, cap in scopes:
        result = db.execute(
            update(QuestionUsage)
            .where(
                QuestionUsage.usage_date == current_date,
                QuestionUsage.scope == scope,
                QuestionUsage.question_count < cap,
            )
            .values(question_count=QuestionUsage.question_count + 1)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            savepoint.rollback()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=_LIMIT_MESSAGES[kind],
                headers={"Retry-After": retry_after},
            )
    savepoint.commit()
    db.expire_all()


def release_question(db: Session, user_id: str, now: datetime | None = None, *, org_id: str | None = None) -> None:
    """Refund a reservation when generation failed and no answer was returned."""
    current_date = _today(now)
    for _, scope, _ in _scopes(user_id, org_id):
        db.execute(
            update(QuestionUsage)
            .where(
                QuestionUsage.usage_date == current_date,
                QuestionUsage.scope == scope,
                QuestionUsage.question_count > 0,
            )
            .values(question_count=QuestionUsage.question_count - 1)
            .execution_options(synchronize_session=False)
        )
    db.flush()
