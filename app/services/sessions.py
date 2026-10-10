"""Refresh sessions behind an httpOnly cookie.

The browser keeps a random 32-byte value in a cookie that page scripts cannot
read; the database keeps only its SHA-256. Each refresh slides the expiry
forward (up to a 90-day absolute limit) and hands back a fresh 30-minute access
token. Revoking a session (sign out, password change, reset, removal from the
workspace) ends it at the next refresh; `users.tokens_valid_after` ends the
access tokens already handed out.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.models import User, UserSession

settings = get_settings()
ABSOLUTE_LIMIT = timedelta(days=90)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create(db: Session, user: User, user_agent: str | None) -> str:
    raw = secrets.token_urlsafe(32)
    now = _now()
    db.add(UserSession(user_id=user.id, token_hash=hash_token(raw), user_agent=(user_agent or "")[:200],
                       created_at=now, last_used_at=now, expires_at=now + timedelta(days=settings.session_days)))
    db.commit()
    return raw


def resume(db: Session, raw: str | None) -> User | None:
    """The user behind a valid cookie (and slide its expiry), else None."""
    if not raw:
        return None
    session = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(raw)))
    now = _now()
    if session is None or session.revoked_at is not None or _utc(session.expires_at) <= now:
        return None
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None
    session.last_used_at = now
    session.expires_at = min(now + timedelta(days=settings.session_days), _utc(session.created_at) + ABSOLUTE_LIMIT)
    db.commit()
    return user


def revoke(db: Session, raw: str | None) -> None:
    if raw:
        db.execute(update(UserSession).where(UserSession.token_hash == hash_token(raw), UserSession.revoked_at.is_(None))
                   .values(revoked_at=_now()))
        db.commit()


def revoke_all(db: Session, user: User) -> None:
    """End every session and every access token issued so far."""
    now = _now()
    db.execute(update(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
               .values(revoked_at=now))
    # A millisecond back, so the replacement token issued right after this
    # (password change, reset) can never land on the cut-off itself.
    user.tokens_valid_after = now - timedelta(milliseconds=1)


def active_count(db: Session, user: User) -> int:
    rows = db.scalars(select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))).all()
    return sum(1 for s in rows if _utc(s.expires_at) > _now())
