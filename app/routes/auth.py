"""Auth routes: signup (always creates a NEW org), login, and invite acceptance.

Signup never looks an org up by name. It used to, which let anyone join any
org (and read its documents) by typing the org's name. The only way into an
existing org is now a single-use invite created by an admin.
"""
import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from slowapi.util import get_remote_address
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password_or_dummy
from app.models.models import Org, OrgInvite, User
from app.models.schemas import AcceptInviteRequest, InvitePreview, SignupRequest, TokenResponse
from app.routes.chat import limiter
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])

INVITE_INVALID = "This invite link is invalid, expired, or has already been used."


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_invite_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _email_taken(db: Session, email: str) -> bool:
    return db.scalar(select(User.id).where(func.lower(User.email) == email)) is not None


def _as_utc(value: datetime) -> datetime:
    # SQLite returns naive datetimes even for timezone=True columns.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute", key_func=get_remote_address)
def signup(request: Request, body: SignupRequest, db: Session = Depends(get_db)):
    email = normalize_email(body.email)
    if _email_taken(db, email):
        raise HTTPException(status_code=409, detail="Email already registered")

    org = Org(name=body.org_name.strip())
    db.add(org)
    db.flush()

    user = User(email=email, hashed_password=hash_password(body.password), org_id=org.id, role="OWNER")
    db.add(user)
    db.flush()
    audit.record(db, org_id=org.id, actor_id=user.id, action="org.created", target_type="org", target_id=org.id)
    db.commit()

    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute", key_func=get_remote_address)
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    email = normalize_email(form.username)
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    valid = verify_password_or_dummy(form.password, user.hashed_password if user else None)
    if user is None or not valid or not user.is_active:
        # Same error and same bcrypt cost either way — don't reveal which part was wrong
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    return TokenResponse(access_token=create_access_token(user.id))


def _load_open_invite(db: Session, token: str, *, lock: bool) -> OrgInvite:
    query = select(OrgInvite).where(OrgInvite.token_hash == hash_invite_token(token))
    if lock:
        # Serialises concurrent accepts of the same invite on Postgres.
        query = query.with_for_update()
    invite = db.scalar(query)
    if (
        invite is None
        or invite.accepted_at is not None
        or invite.revoked_at is not None
        or _as_utc(invite.expires_at) <= datetime.now(timezone.utc)
    ):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=INVITE_INVALID)
    return invite


@router.get("/invites/{token}", response_model=InvitePreview)
@limiter.limit("30/minute", key_func=get_remote_address)
def preview_invite(request: Request, token: str, db: Session = Depends(get_db)):
    invite = _load_open_invite(db, token, lock=False)
    org = db.get(Org, invite.org_id)
    return InvitePreview(org_name=org.name, email=invite.email, role=invite.role)


@router.post("/accept-invite", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute", key_func=get_remote_address)
def accept_invite(request: Request, body: AcceptInviteRequest, db: Session = Depends(get_db)):
    """Create the invited account and burn the invite in ONE transaction.

    Two guards make the invite single-use even under concurrent requests:
    1. SELECT ... FOR UPDATE locks the invite row (Postgres).
    2. The burn is a conditional UPDATE ... WHERE accepted_at IS NULL, and we
       require exactly one row changed. That holds on every database, so a
       second accept can never create a second account.
    """
    invite = _load_open_invite(db, body.token, lock=True)

    if _email_taken(db, invite.email):
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    now = datetime.now(timezone.utc)
    burned = db.execute(
        update(OrgInvite)
        .where(OrgInvite.id == invite.id, OrgInvite.accepted_at.is_(None), OrgInvite.revoked_at.is_(None))
        .values(accepted_at=now)
    )
    if burned.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=INVITE_INVALID)

    user = User(
        email=invite.email,
        hashed_password=hash_password(body.password),
        org_id=invite.org_id,
        role=invite.role,
    )
    db.add(user)
    db.flush()
    audit.record(
        db,
        org_id=invite.org_id,
        actor_id=user.id,
        action="invite.accepted",
        target_type="invite",
        target_id=invite.id,
        details={"role": invite.role},
    )
    db.commit()
    return TokenResponse(access_token=create_access_token(user.id))
