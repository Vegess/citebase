"""Sign in with Google or GitHub (OAuth 2.0 authorization-code flow).

Flow
1. Browser → GET /auth/oauth/{provider}/start
   We create a random nonce, put it in a short-lived httpOnly cookie, and send
   the browser to the provider with state = signed JWT {provider, nonce, next}.
2. Provider → GET /auth/oauth/{provider}/callback?code&state
   We verify the state signature and that its nonce matches the cookie (stops
   login-CSRF: an attacker can't make your browser finish *their* sign-in),
   exchange the code server-side, and read a *verified* email address.
3. We find the account for that email, or create one:
   - an open invite for that email → join the inviting workspace with that role
     (the provider has verified the address, so this is safe);
   - otherwise → a new workspace with the user as OWNER (same rule as signup:
     never join an existing org by name).
4. Browser → {FRONTEND_URL}/auth/callback#token=...
   The token rides in the URL fragment, which browsers never send to servers
   or put in Referer headers.

A provider is enabled only when its client id and secret are configured;
GET /auth/providers tells the frontend which buttons to activate.
"""
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.models.models import Org, OrgInvite, User
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

STATE_TTL = timedelta(minutes=10)
NONCE_COOKIE = "documind_oauth_nonce"

PROVIDERS = {
    "google": {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "scope": "openid email profile",
    },
    "github": {
        "authorize": "https://github.com/login/oauth/authorize",
        "token": "https://github.com/login/oauth/access_token",
        "scope": "read:user user:email",
    },
}


def _credentials(provider: str) -> tuple[str | None, str | None]:
    if provider == "google":
        return settings.google_client_id, settings.google_client_secret
    if provider == "github":
        return settings.github_client_id, settings.github_client_secret
    return None, None


def enabled_providers() -> list[str]:
    return [p for p in PROVIDERS if all(_credentials(p))]


def _callback_url(provider: str) -> str:
    return f"{settings.api_public_url.rstrip('/')}/auth/oauth/{provider}/callback"


def _frontend(path: str) -> str:
    return f"{settings.frontend_url.rstrip('/')}{path}"


def _fail(reason: str) -> RedirectResponse:
    response = RedirectResponse(_frontend("/auth/callback#" + urlencode({"error": reason})), status_code=302)
    response.delete_cookie(NONCE_COOKIE, path="/auth/oauth")
    return response


@router.get("/providers")
def list_providers():
    return {"providers": enabled_providers()}


@router.get("/oauth/{provider}/start")
def oauth_start(provider: str):
    if provider not in PROVIDERS or provider not in enabled_providers():
        raise HTTPException(status_code=404, detail=f"{provider} sign-in is not set up on this server.")
    client_id, _ = _credentials(provider)
    nonce = secrets.token_urlsafe(24)
    state = jwt.encode(
        {"p": provider, "n": nonce, "exp": datetime.now(timezone.utc) + STATE_TTL},
        settings.jwt_secret_key, algorithm="HS256",
    )
    params = {
        "client_id": client_id,
        "redirect_uri": _callback_url(provider),
        "response_type": "code",
        "scope": PROVIDERS[provider]["scope"],
        "state": state,
    }
    if provider == "google":
        params["prompt"] = "select_account"
    response = RedirectResponse(f"{PROVIDERS[provider]['authorize']}?{urlencode(params)}", status_code=302)
    response.set_cookie(
        NONCE_COOKIE, nonce, max_age=int(STATE_TTL.total_seconds()), httponly=True,
        secure=settings.api_public_url.startswith("https"), samesite="lax", path="/auth/oauth",
    )
    return response


def _exchange_code(provider: str, code: str) -> str:
    client_id, client_secret = _credentials(provider)
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": _callback_url(provider),
        "grant_type": "authorization_code",
    }
    resp = httpx.post(PROVIDERS[provider]["token"], data=data, headers={"Accept": "application/json"}, timeout=15)
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise ValueError("no access token in provider response")
    return token


def fetch_verified_email(provider: str, access_token: str) -> tuple[str, str | None]:
    """Return (email, display name). Raises ValueError if no verified email."""
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    if provider == "google":
        info = httpx.get("https://openidconnect.googleapis.com/v1/userinfo", headers=headers, timeout=15).json()
        if not info.get("email") or not info.get("email_verified"):
            raise ValueError("Google account has no verified email")
        return info["email"], info.get("name")
    profile = httpx.get("https://api.github.com/user", headers=headers, timeout=15).json()
    emails = httpx.get("https://api.github.com/user/emails", headers=headers, timeout=15).json()
    primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
    if primary is None:
        raise ValueError("GitHub account has no verified primary email")
    return primary["email"], profile.get("name") or profile.get("login")


def sign_in_with_email(db: Session, provider: str, email: str, name: str | None) -> User:
    """Find or create the account for a provider-verified email."""
    email = email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is not None:
        if not user.is_active:
            raise PermissionError("This account has been removed from its workspace.")
        return user

    now = datetime.now(timezone.utc)
    invite = db.scalar(
        select(OrgInvite)
        .where(OrgInvite.email == email, OrgInvite.accepted_at.is_(None), OrgInvite.revoked_at.is_(None),
               OrgInvite.expires_at > now)
        .order_by(OrgInvite.created_at.desc())
        .with_for_update()
    )
    # No password: the stored hash is of a random secret nobody knows.
    unusable = hash_password(secrets.token_urlsafe(32))
    if invite is not None:
        invite.accepted_at = now
        user = User(email=email, hashed_password=unusable, org_id=invite.org_id, role=invite.role)
        db.add(user)
        db.flush()
        audit.record(db, org_id=invite.org_id, actor_id=user.id, action="invite.accepted",
                     target_type="invite", target_id=invite.id, details={"role": invite.role, "via": provider})
    else:
        org_name = f"{name}'s workspace" if name else f"{email.split('@')[0]}'s workspace"
        org = Org(name=org_name[:120])
        db.add(org)
        db.flush()
        user = User(email=email, hashed_password=unusable, org_id=org.id, role="OWNER")
        db.add(user)
        db.flush()
        audit.record(db, org_id=org.id, actor_id=user.id, action="org.created", target_type="org",
                     target_id=org.id, details={"via": provider})
    db.commit()
    return user


@router.get("/oauth/{provider}/callback")
def oauth_callback(provider: str, request: Request, code: str | None = None, state: str | None = None,
                   error: str | None = None, db: Session = Depends(get_db)):
    if provider not in enabled_providers():
        return _fail("provider_disabled")
    if error or not code or not state:
        return _fail("cancelled")
    try:
        claims = jwt.decode(state, settings.jwt_secret_key, algorithms=["HS256"])
    except JWTError:
        return _fail("expired")
    cookie_nonce = request.cookies.get(NONCE_COOKIE)
    if claims.get("p") != provider or not cookie_nonce or not secrets.compare_digest(cookie_nonce, claims.get("n", "")):
        return _fail("state_mismatch")

    try:
        email, name = fetch_verified_email(provider, _exchange_code(provider, code))
    except ValueError:
        return _fail("no_verified_email")
    except httpx.HTTPError:
        return _fail("provider_error")

    try:
        user = sign_in_with_email(db, provider, email, name)
    except PermissionError:
        return _fail("account_removed")

    response = RedirectResponse(
        _frontend("/auth/callback#" + urlencode({"token": create_access_token(user.id)})), status_code=302)
    response.delete_cookie(NONCE_COOKIE, path="/auth/oauth")
    return response
