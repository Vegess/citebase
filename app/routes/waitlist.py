"""Waitlist routes: public access requests and platform-admin review.

POST /auth/access-requests always gives the same reply, whether the email is
new, already waiting, or already has an account, so it can't be used to
find out who uses Citebase.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import AccessRequest, User
from app.models.schemas import AccessPreview, AccessRequestCreate, AccessRequestOut
from app.routes.auth import ACCESS_INVALID, _email_taken, normalize_email
from app.routes.chat import limiter
from app.services import mailer, waitlist

settings = get_settings()
logger = logging.getLogger("app.routes.waitlist")

public = APIRouter(prefix="/auth", tags=["auth"])
admin = APIRouter(prefix="/admin", tags=["admin"])

REQUEST_RECEIVED = {"detail": "Thanks. If this email can be given access, we'll email you a sign-up link."}


@public.get("/signup-config")
def signup_config():
    return {"mode": settings.signup_mode}


def _frontend(path: str) -> str:
    return f"{settings.frontend_url.rstrip('/')}{path}"


def _notify_admins(email: str, name: str, company: str | None, reason: str | None) -> None:
    text = (
        f"{name} <{email}> asked for access to Citebase.\n"
        f"Company: {company or '-'}\n"
        f"Reason: {reason or '-'}\n\n"
        f"Review it at {_frontend('/admin/access')}\n"
    )
    for to in sorted(settings.platform_admins):
        mailer.send(to, "New Citebase access request", text)


@public.post("/access-requests", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/hour", key_func=get_remote_address)
def request_access(request: Request, body: AccessRequestCreate, background: BackgroundTasks,
                   db: Session = Depends(get_db)):
    email = normalize_email(body.email)
    already_waiting = db.scalar(
        select(AccessRequest.id).where(AccessRequest.email == email, AccessRequest.status.in_(("pending", "approved")))
    )
    if already_waiting is None and not _email_taken(db, email):
        name = body.name.strip()
        company = (body.company or "").strip() or None
        reason = (body.reason or "").strip() or None
        db.add(AccessRequest(email=email, name=name, company=company, reason=reason))
        try:
            db.commit()
        except IntegrityError:  # a concurrent request for the same email won
            db.rollback()
        else:
            # After the response, so a new email isn't slower to answer than a known one.
            background.add_task(_notify_admins, email, name, company, reason)
    return REQUEST_RECEIVED


@public.get("/access/{token}", response_model=AccessPreview)
@limiter.limit("30/minute", key_func=get_remote_address)
def preview_access(request: Request, token: str, db: Session = Depends(get_db)):
    access = waitlist.load_by_token(db, token)
    if access is None:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=ACCESS_INVALID)
    return AccessPreview(email=access.email, name=access.name)


# ---- Platform admin ----

def require_platform_admin(user: User = Depends(get_current_user)) -> User:
    if not waitlist.is_platform_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform admins only.")
    return user


def _request_or_404(db: Session, request_id: str) -> AccessRequest:
    access = db.scalar(select(AccessRequest).where(AccessRequest.id == request_id).with_for_update())
    if access is None:
        raise HTTPException(status_code=404, detail="Access request not found")
    return access


@admin.get("/access-requests", response_model=list[AccessRequestOut])
def list_access_requests(status_filter: str | None = Query(None, alias="status"), _: User = Depends(require_platform_admin),
                         db: Session = Depends(get_db)):
    query = select(AccessRequest).order_by(AccessRequest.created_at.desc()).limit(500)
    if status_filter in ("pending", "approved", "rejected"):
        query = query.where(AccessRequest.status == status_filter)
    return db.scalars(query).all()


@admin.post("/access-requests/{request_id}/approve")
def approve_access_request(request_id: str, actor: User = Depends(require_platform_admin),
                           db: Session = Depends(get_db)):
    """Approve (or re-send a fresh link for) a request. The link is single-use, valid 7 days."""
    access = _request_or_404(db, request_id)
    if _email_taken(db, access.email):
        db.rollback()
        raise HTTPException(status_code=409, detail="This email already has an account.")
    raw = waitlist.issue_token(access)
    access.status = "approved"
    access.decided_at = datetime.now(timezone.utc)
    access.decided_by = actor.id
    db.commit()
    db.refresh(access)

    link = _frontend(f"/signup#access={raw}")
    emailed = mailer.send(
        access.email,
        "Your Citebase access is approved",
        f"Hi {access.name},\n\nYou're in. Create your Citebase account with this link "
        f"(it works once and expires in 7 days):\n\n{link}\n",
    )
    logger.info("access request approved", extra={"request_id": access.id, "emailed": emailed})
    return {
        "request": AccessRequestOut.model_validate(access),
        "emailed": emailed,
        # Without email delivery the admin passes the link on by hand.
        "link": None if emailed else link,
    }


@admin.post("/access-requests/{request_id}/reject", response_model=AccessRequestOut)
def reject_access_request(request_id: str, actor: User = Depends(require_platform_admin),
                          db: Session = Depends(get_db)):
    access = _request_or_404(db, request_id)
    access.status = "rejected"
    access.token_hash = None
    access.token_expires_at = None
    access.decided_at = datetime.now(timezone.utc)
    access.decided_by = actor.id
    db.commit()
    db.refresh(access)
    return access
