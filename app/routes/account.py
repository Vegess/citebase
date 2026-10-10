"""Sessions that survive a refresh, password reset, and account settings.

Session endpoints are called through the frontend's own origin (Vercel
rewrites /api/* to this API), so the httpOnly cookie is first-party and is
never readable by page scripts. Every cookie-authenticated POST also requires
an `X-Requested-With: citebase` header, which a cross-site form can't send.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from slowapi.util import get_remote_address
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_access_token, get_current_user, hash_password, verify_password
from app.models.models import User, UserIdentity
from app.routes.chat import limiter
from app.routes.oauth import enabled_providers, link_start_url
from app.services import audit, mailer, resets, sessions

router = APIRouter(tags=["account"])
settings = get_settings()

SESSION_COOKIE = "citebase_session"


def _csrf_guard(x_requested_with: str | None = Header(default=None)) -> None:
    if x_requested_with != "citebase":
        raise HTTPException(status_code=403, detail="Missing request header.")


def _set_cookie(response: Response, raw: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, raw, max_age=settings.session_days * 86400, httponly=True,
        secure=settings.frontend_url.startswith("https"), samesite="lax", path=settings.session_cookie_path,
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path=settings.session_cookie_path)


# ---- Sessions ----

@router.post("/auth/session", status_code=204, dependencies=[Depends(_csrf_guard)])
def start_session(request: Request, response: Response, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Turn a fresh access token into a long-lived cookie session."""
    sessions.revoke(db, request.cookies.get(SESSION_COOKIE))  # replace any older one in this browser
    _set_cookie(response, sessions.create(db, user, request.headers.get("user-agent")))


def _session_key(request: Request) -> str:
    # These calls arrive through the frontend's proxy, so many users share an IP;
    # limit per session instead.
    raw = request.cookies.get(SESSION_COOKIE)
    return f"session:{raw[:16]}" if raw else f"ip:{get_remote_address(request)}"


@router.post("/auth/refresh", dependencies=[Depends(_csrf_guard)])
@limiter.limit("60/minute", key_func=_session_key)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    user = sessions.resume(db, request.cookies.get(SESSION_COOKIE))
    if user is None:
        _clear_cookie(response)
        raise HTTPException(status_code=401, detail="Session expired")
    return {"access_token": create_access_token(user.id), "token_type": "bearer"}


@router.post("/auth/logout", status_code=204, dependencies=[Depends(_csrf_guard)])
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    sessions.revoke(db, request.cookies.get(SESSION_COOKIE))
    _clear_cookie(response)


# ---- Password reset ----

class ForgotPassword(BaseModel):
    email: EmailStr


class ResetPassword(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=8, max_length=128)


@router.post("/auth/forgot-password", status_code=202)
@limiter.limit("5/minute")
def forgot_password(request: Request, body: ForgotPassword, db: Session = Depends(get_db)):
    """Always the same answer, so nobody can probe which emails have accounts."""
    if mailer.enabled():
        user = db.scalar(select(User).where(func.lower(User.email) == body.email.strip().lower()))
        if user is not None and user.is_active:
            raw = resets.create(db, user, via="email")
            db.commit()
            link = f"{settings.frontend_url.rstrip('/')}/reset-password#{raw}"
            mailer.send(user.email, "Reset your Citebase password",
                        f"Someone asked to reset the password for {user.email}.\n\n"
                        f"Choose a new password here (valid for 1 hour, works once):\n{link}\n\n"
                        "If this wasn't you, ignore this email; your password stays the same.")
    return {"email_enabled": mailer.enabled()}


@router.get("/auth/password-reset/{token}")
@limiter.limit("20/minute")
def preview_reset(request: Request, token: str, db: Session = Depends(get_db)):
    reset = resets.peek(db, token)
    if reset is None:
        raise HTTPException(status_code=404, detail="This reset link is invalid, used or expired.")
    return {"email": db.get(User, reset.user_id).email}


@router.post("/auth/password-reset")
@limiter.limit("10/minute")
def reset_password(request: Request, body: ResetPassword, db: Session = Depends(get_db)):
    reset = resets.consume(db, body.token)
    user = db.get(User, reset.user_id) if reset else None
    if user is None or not user.is_active:
        db.rollback()
        raise HTTPException(status_code=400, detail="This reset link is invalid, used or expired.")
    user.hashed_password = hash_password(body.password)
    user.password_set = True
    if reset.via == "email" and user.email_verified_at is None:
        user.email_verified_at = datetime.now(timezone.utc)  # they read the inbox: the email is theirs
    sessions.revoke_all(db, user)
    audit.record(db, org_id=user.org_id, actor_id=user.id, action="account.password_reset",
                 target_type="user", target_id=user.id, details={"via": reset.via})
    db.commit()
    return {"access_token": create_access_token(user.id), "token_type": "bearer"}


# ---- Email verification ----

def send_verification(db: Session, user: User) -> bool:
    raw = resets.create(db, user, via="verify")
    db.commit()
    link = f"{settings.frontend_url.rstrip('/')}/verify-email#{raw}"
    return mailer.send(user.email, "Confirm your email for Citebase",
                       f"Confirm that {user.email} is yours (link valid for 1 hour):\n{link}\n\n"
                       "Until you do, you can use Citebase but can't invite teammates.")


class VerifyEmail(BaseModel):
    token: str = Field(min_length=10, max_length=200)


@router.post("/account/verify-email", status_code=202)
@limiter.limit("3/minute")
def request_verification(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.email_verified_at is not None:
        return {"sent": False, "already_verified": True}
    if not mailer.enabled():
        raise HTTPException(status_code=503, detail="Email isn't set up on this server yet.")
    if not send_verification(db, user):
        raise HTTPException(status_code=502, detail="The email couldn't be sent. Try again in a minute.")
    return {"sent": True}


@router.post("/auth/verify-email")
@limiter.limit("10/minute")
def confirm_email(request: Request, body: VerifyEmail, db: Session = Depends(get_db)):
    token = resets.consume(db, body.token, purposes=("verify",))
    user = db.get(User, token.user_id) if token else None
    if user is None or not user.is_active:
        db.rollback()
        raise HTTPException(status_code=400, detail="This link is invalid, used or expired.")
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(timezone.utc)
        audit.record(db, org_id=user.org_id, actor_id=user.id, action="account.email_verified",
                     target_type="user", target_id=user.id)
    db.commit()
    return {"email": user.email}


# ---- Account settings ----

class ChangePassword(BaseModel):
    current_password: str | None = Field(default=None, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


@router.get("/account")
def read_account(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    identities = db.scalars(select(UserIdentity).where(UserIdentity.user_id == user.id)).all()
    return {
        "email": user.email,
        "role": user.role,
        "org_name": user.org.name if user.org else None,
        "password_set": user.password_set,
        "email_verified": user.email_verified_at is not None,
        "identities": [{"provider": i.provider, "email": i.email} for i in identities],
        "available_providers": enabled_providers(),
        "active_sessions": sessions.active_count(db, user),
        "email_enabled": mailer.enabled(),
    }


@router.post("/account/password")
@limiter.limit("10/minute")
def change_password(request: Request, body: ChangePassword, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if user.password_set and not (body.current_password and verify_password(body.current_password, user.hashed_password)):
        raise HTTPException(status_code=400, detail="Your current password isn't right.")
    user.hashed_password = hash_password(body.new_password)
    user.password_set = True
    sessions.revoke_all(db, user)
    audit.record(db, org_id=user.org_id, actor_id=user.id, action="account.password_changed",
                 target_type="user", target_id=user.id)
    db.commit()
    # Every other device is signed out; this one continues with a new token.
    return {"access_token": create_access_token(user.id), "token_type": "bearer"}


@router.post("/account/sign-out-everywhere", status_code=204)
def sign_out_everywhere(response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sessions.revoke_all(db, user)
    db.commit()
    _clear_cookie(response)


@router.post("/account/link/{provider}")
def start_link(provider: str, user: User = Depends(get_current_user)):
    if provider not in enabled_providers():
        raise HTTPException(status_code=404, detail=f"{provider} isn't set up on this server.")
    return {"url": link_start_url(user, provider)}


@router.delete("/account/identities/{provider}", status_code=204)
def unlink(provider: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    remaining = db.scalars(select(UserIdentity).where(UserIdentity.user_id == user.id)).all()
    if not user.password_set and len(remaining) <= 1:
        raise HTTPException(status_code=400, detail="Set a password first, or you'd have no way to sign in.")
    db.execute(delete(UserIdentity).where(UserIdentity.user_id == user.id, UserIdentity.provider == provider))
    audit.record(db, org_id=user.org_id, actor_id=user.id, action="account.provider_unlinked",
                 target_type="user", target_id=user.id, details={"provider": provider})
    db.commit()
