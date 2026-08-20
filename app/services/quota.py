"""Persistent daily question quotas."""
from datetime import date, datetime, timedelta, timezone
from math import ceil

from fastapi import HTTPException, status
from sqlalchemy import select
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


def reserve_question(db: Session, user_id: str, now: datetime | None = None) -> None:
    """Reserve one question or raise a daily-quota HTTP 429."""
    current_date = _today(now)
    global_usage = _get_usage(db, current_date, GLOBAL_SCOPE)
    user_usage = _get_usage(db, current_date, user_id)
    retry_after = str(_retry_after(now))

    if global_usage.question_count >= settings.daily_question_cap:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="This demo has reached its daily AI quota. Please try again tomorrow.",
            headers={"Retry-After": retry_after},
        )
    if user_usage.question_count >= settings.per_user_daily_cap:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You've reached your daily question limit for this demo. Please try again tomorrow.",
            headers={"Retry-After": retry_after},
        )

    global_usage.question_count += 1
    user_usage.question_count += 1
    db.flush()

    

def release_question(db: Session, user_id: str, now: datetime | None = None) -> None:
    """Refund a reservation when generation failed and no answer was returned."""
    current_date = _today(now)
    global_usage = _get_usage(db, current_date, GLOBAL_SCOPE)
    user_usage = _get_usage(db, current_date, user_id)

    global_usage.question_count = max(0, global_usage.question_count - 1)
    user_usage.question_count = max(0, user_usage.question_count - 1)
    db.flush()
