"""Single-use password-reset tokens: random, stored as SHA-256, valid for 1 hour."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.models import PasswordReset, User

TTL = timedelta(hours=1)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create(db: Session, user: User, via: str, created_by: str | None = None) -> str:
    raw = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    db.add(PasswordReset(user_id=user.id, token_hash=_hash(raw), via=via, created_by=created_by,
                         created_at=now, expires_at=now + TTL))
    return raw


def peek(db: Session, raw: str) -> PasswordReset | None:
    reset = db.scalar(select(PasswordReset).where(PasswordReset.token_hash == _hash(raw)))
    if reset is None or reset.used_at is not None:
        return None
    expires = reset.expires_at if reset.expires_at.tzinfo else reset.expires_at.replace(tzinfo=timezone.utc)
    return reset if expires > datetime.now(timezone.utc) else None


def consume(db: Session, raw: str) -> PasswordReset | None:
    """Mark the token used, atomically: two concurrent requests can't both use it."""
    reset = peek(db, raw)
    if reset is None:
        return None
    claimed = db.execute(
        update(PasswordReset)
        .where(PasswordReset.id == reset.id, PasswordReset.used_at.is_(None))
        .values(used_at=datetime.now(timezone.utc))
    ).rowcount
    return reset if claimed == 1 else None
