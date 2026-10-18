"""Invite-only launch (SIGNUP_MODE=waitlist).

People ask for access; a platform admin (PLATFORM_ADMIN_EMAILS) approves or
rejects. Approval emails a single-use sign-up link valid for 7 days. Only the
SHA-256 of the token is stored, and it is cleared the moment it is used.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.models import AccessRequest, User

settings = get_settings()
TOKEN_TTL = timedelta(days=7)


def enabled() -> bool:
    return settings.signup_mode == "waitlist"


def is_platform_admin(user: User) -> bool:
    # The email must be proven, or anyone could sign up as the admin's address
    # before the admin does.
    return user.email.lower() in settings.platform_admins and user.email_verified_at is not None


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_token(request: AccessRequest) -> str:
    raw = secrets.token_urlsafe(32)
    request.token_hash = hash_token(raw)
    request.token_expires_at = datetime.now(timezone.utc) + TOKEN_TTL
    return raw


def load_by_token(db: Session, raw: str) -> AccessRequest | None:
    """The approved request behind an unused, unexpired token, else None."""
    request = db.scalar(select(AccessRequest).where(AccessRequest.token_hash == hash_token(raw)))
    if request is None or request.status != "approved" or request.token_expires_at is None:
        return None
    expires = request.token_expires_at
    if expires.tzinfo is None:  # SQLite drops the timezone
        expires = expires.replace(tzinfo=timezone.utc)
    return request if expires > datetime.now(timezone.utc) else None


def consume_token(db: Session, request: AccessRequest, raw: str) -> bool:
    """Burn the token atomically: two concurrent sign-ups can't both use it."""
    burned = db.execute(
        update(AccessRequest)
        .where(AccessRequest.id == request.id, AccessRequest.token_hash == hash_token(raw))
        .values(token_hash=None)
    )
    return burned.rowcount == 1


def approved_request_for(db: Session, email: str) -> AccessRequest | None:
    return db.scalar(
        select(AccessRequest)
        .where(AccessRequest.email == email, AccessRequest.status == "approved")
        .order_by(AccessRequest.decided_at.desc())
    )
