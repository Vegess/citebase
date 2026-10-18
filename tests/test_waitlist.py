"""Invite-only launch: SIGNUP_MODE=waitlist, access requests, platform admins."""
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

PASSWORD = "password123"
ADMIN = "boss@citebase.app"


@pytest.fixture()
def settings(app_client, monkeypatch):
    from app.core.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "platform_admin_emails", f"{ADMIN}, Second@Citebase.app")
    return s


@pytest.fixture()
def waitlist(settings, monkeypatch):
    monkeypatch.setattr(settings, "signup_mode", "waitlist")
    return settings


@pytest.fixture()
def sent(monkeypatch):
    from app.services import mailer

    outbox = []
    monkeypatch.setattr(mailer, "send", lambda to, subject, text: outbox.append((to, subject, text)) or True)
    return outbox


def _db():
    import app.core.database as database
    return database.SessionLocal()


def _signup(client, email, access_token=None, org="Acme"):
    body = {"email": email, "password": PASSWORD, "org_name": org}
    if access_token:
        body["access_token"] = access_token
    return client.post("/auth/signup", json=body)


def _headers(resp):
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _platform_admin(client, settings, monkeypatch):
    """Created in open mode, with a verified email (as after a provider sign-in)."""
    from app.models.models import User

    monkeypatch.setattr(settings, "signup_mode", "open")
    headers = _headers(_signup(client, ADMIN, org="Citebase HQ"))
    with _db() as db:
        db.scalar(select(User).where(User.email == ADMIN)).email_verified_at = datetime.now(timezone.utc)
        db.commit()
    return headers


def _request(client, email="Jane@Example.com", **extra):
    return client.post("/auth/access-requests", json={"email": email, "name": "Jane", **extra})


def _pending_id(client, admin, email="jane@example.com"):
    rows = client.get("/admin/access-requests?status=pending", headers=admin).json()
    return next(r["id"] for r in rows if r["email"] == email)


def _approve(client, admin, email="jane@example.com"):
    resp = client.post(f"/admin/access-requests/{_pending_id(client, admin, email)}/approve", headers=admin)
    assert resp.status_code == 200, resp.text
    return parse_qs(urlparse(resp.json()["link"]).fragment)["access"][0]


# ---- mode ----

def test_signup_config_defaults_to_open(app_client):
    assert app_client.get("/auth/signup-config").json() == {"mode": "open"}


def test_open_mode_allows_password_signup_without_token(settings, app_client):
    assert _signup(app_client, "free@acme.com").status_code == 201


def test_waitlist_mode_is_reported_and_blocks_plain_signup(waitlist, app_client):
    assert app_client.get("/auth/signup-config").json() == {"mode": "waitlist"}
    resp = _signup(app_client, "free@acme.com")
    assert resp.status_code == 403 and "invite-only" in resp.json()["detail"]


def test_existing_users_can_always_sign_in(settings, app_client, monkeypatch):
    _signup(app_client, "old@acme.com")
    monkeypatch.setattr(settings, "signup_mode", "waitlist")
    resp = app_client.post("/auth/login", data={"username": "old@acme.com", "password": PASSWORD})
    assert resp.status_code == 200


# ---- access requests ----

def test_request_reply_is_uniform(waitlist, app_client, monkeypatch):
    _platform_admin(app_client, waitlist, monkeypatch)
    monkeypatch.setattr(waitlist, "signup_mode", "waitlist")
    new = _request(app_client)
    repeat = _request(app_client, "jane@example.com")
    existing_user = _request(app_client, ADMIN)
    assert new.status_code == repeat.status_code == existing_user.status_code == 202
    assert new.json() == repeat.json() == existing_user.json()


def test_request_is_stored_lower_cased_once_and_admins_are_emailed(waitlist, app_client, sent):
    from app.models.models import AccessRequest

    _request(app_client, "  Jane@Example.COM ", company="Acme", reason="HR policies")
    _request(app_client, "jane@example.com")
    with _db() as db:
        rows = db.scalars(select(AccessRequest)).all()
    assert [(r.email, r.status, r.company) for r in rows] == [("jane@example.com", "pending", "Acme")]
    assert sorted(to for to, _, _ in sent) == [ADMIN, "second@citebase.app"]
    assert "jane@example.com" in sent[0][2] and "/admin/access" in sent[0][2]


def test_no_admin_email_for_existing_account(settings, app_client, sent):
    _signup(app_client, "old@acme.com")
    assert _request(app_client, "old@acme.com").status_code == 202
    assert sent == []


def test_rejected_person_can_ask_again(waitlist, app_client, monkeypatch):
    admin = _platform_admin(app_client, waitlist, monkeypatch)
    _request(app_client)
    app_client.post(f"/admin/access-requests/{_pending_id(app_client, admin)}/reject", headers=admin)
    _request(app_client)
    rows = app_client.get("/admin/access-requests", headers=admin).json()
    assert sorted(r["status"] for r in rows) == ["pending", "rejected"]


def test_access_requests_are_rate_limited_per_ip(waitlist, app_client):
    codes = [_request(app_client, f"p{i}@example.com").status_code for i in range(6)]
    assert codes == [202] * 5 + [429]


# ---- admin routes ----

def test_admin_routes_need_a_platform_admin(waitlist, app_client, monkeypatch):
    _request(app_client)
    assert app_client.get("/admin/access-requests").status_code == 401

    monkeypatch.setattr(waitlist, "signup_mode", "open")
    owner = _headers(_signup(app_client, "owner@acme.com"))  # workspace OWNER, not platform admin
    assert app_client.get("/admin/access-requests", headers=owner).status_code == 403
    assert app_client.get("/me", headers=owner).json()["is_platform_admin"] is False

    with _db() as db:
        from app.models.models import AccessRequest
        request_id = db.scalar(select(AccessRequest.id))
    assert app_client.post(f"/admin/access-requests/{request_id}/approve", headers=owner).status_code == 403
    assert app_client.post(f"/admin/access-requests/{request_id}/reject", headers=owner).status_code == 403


def test_admin_email_must_be_verified(settings, app_client):
    unverified = _headers(_signup(app_client, ADMIN))  # squatting the admin's address proves nothing
    assert app_client.get("/admin/access-requests", headers=unverified).status_code == 403


def test_platform_admin_lists_and_rejects(waitlist, app_client, monkeypatch):
    admin = _platform_admin(app_client, waitlist, monkeypatch)
    assert app_client.get("/me", headers=admin).json()["is_platform_admin"] is True
    _request(app_client)
    request_id = _pending_id(app_client, admin)
    rejected = app_client.post(f"/admin/access-requests/{request_id}/reject", headers=admin).json()
    assert rejected["status"] == "rejected" and rejected["decided_at"]
    assert app_client.get("/admin/access-requests?status=pending", headers=admin).json() == []


def test_approve_emails_a_single_use_signup_link(waitlist, app_client, monkeypatch, sent):
    admin = _platform_admin(app_client, waitlist, monkeypatch)
    monkeypatch.setattr(waitlist, "signup_mode", "waitlist")
    monkeypatch.setattr(waitlist, "frontend_url", "https://app.example.com")
    _request(app_client)
    sent.clear()
    resp = app_client.post(f"/admin/access-requests/{_pending_id(app_client, admin)}/approve", headers=admin).json()
    assert resp["emailed"] is True and resp["link"] is None
    assert resp["request"]["status"] == "approved"
    expires = datetime.fromisoformat(resp["request"]["token_expires_at"])
    assert timedelta(days=6, hours=23) < expires.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc) <= timedelta(days=7)
    (to, _, text), = sent
    assert to == "jane@example.com" and "https://app.example.com/signup#access=" in text


def test_approve_without_email_returns_the_link(waitlist, app_client, monkeypatch):
    admin = _platform_admin(app_client, waitlist, monkeypatch)
    _request(app_client)
    token = _approve(app_client, admin)
    assert len(token) > 20


# ---- signing up with the token ----

def test_access_token_locks_the_email_and_is_single_use(waitlist, app_client, monkeypatch):
    admin = _platform_admin(app_client, waitlist, monkeypatch)
    monkeypatch.setattr(waitlist, "signup_mode", "waitlist")
    _request(app_client)
    token = _approve(app_client, admin)

    assert app_client.get(f"/auth/access/{token}").json() == {"email": "jane@example.com", "name": "Jane"}
    assert _signup(app_client, "other@example.com", token).status_code == 400  # email is locked

    resp = _signup(app_client, "Jane@Example.com", token)
    assert resp.status_code == 201
    from app.models.models import User
    with _db() as db:
        assert db.scalar(select(User).where(User.email == "jane@example.com")).email_verified_at is not None

    assert app_client.get(f"/auth/access/{token}").status_code == 410
    assert _signup(app_client, "jane@example.com", token).status_code == 410


def test_expired_access_token_is_refused(waitlist, app_client, monkeypatch):
    from app.models.models import AccessRequest

    admin = _platform_admin(app_client, waitlist, monkeypatch)
    monkeypatch.setattr(waitlist, "signup_mode", "waitlist")
    _request(app_client)
    token = _approve(app_client, admin)
    with _db() as db:
        db.scalar(select(AccessRequest)).token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    assert app_client.get(f"/auth/access/{token}").status_code == 410
    assert _signup(app_client, "jane@example.com", token).status_code == 410


def test_rejecting_revokes_an_issued_token(waitlist, app_client, monkeypatch):
    admin = _platform_admin(app_client, waitlist, monkeypatch)
    _request(app_client)
    request_id = _pending_id(app_client, admin)
    token = _approve(app_client, admin)
    app_client.post(f"/admin/access-requests/{request_id}/reject", headers=admin)
    assert app_client.get(f"/auth/access/{token}").status_code == 410


def test_unknown_token_is_refused(waitlist, app_client):
    assert app_client.get("/auth/access/" + "x" * 40).status_code == 410
    assert _signup(app_client, "jane@example.com", "x" * 40).status_code == 410


# ---- invites ----

def test_team_invites_still_work_in_waitlist_mode(settings, app_client, monkeypatch):
    owner = _headers(_signup(app_client, "owner@acme.com"))
    monkeypatch.setattr(settings, "signup_mode", "waitlist")
    token = app_client.post("/org/invites", json={"email": "hire@acme.com", "role": "MEMBER"},
                            headers=owner).json()["token"]
    resp = app_client.post("/auth/accept-invite", json={"token": token, "password": PASSWORD})
    assert resp.status_code == 201
    assert app_client.get("/me", headers=_headers(resp)).json()["role"] == "MEMBER"


# ---- Google / GitHub ----

@pytest.fixture()
def oauth(waitlist, monkeypatch):
    from app.routes import oauth as oauth_module

    s = oauth_module.settings
    monkeypatch.setattr(s, "google_client_id", "gid")
    monkeypatch.setattr(s, "google_client_secret", "gsecret")
    monkeypatch.setattr(oauth_module, "_exchange_code", lambda provider, code: "tok")
    identity = {"email": "Jane@Example.com", "name": "Jane"}
    monkeypatch.setattr(oauth_module, "fetch_verified_email", lambda p, t: (identity["email"], identity["name"]))
    return identity


def _google(client):
    start = client.get("/auth/oauth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    nonce = start.cookies.get("citebase_oauth_nonce")
    client.cookies.clear()
    client.cookies.set("citebase_oauth_nonce", nonce, path="/auth/oauth")
    resp = client.get(f"/auth/oauth/google/callback?code=c&state={state}", follow_redirects=False)
    return {k: v[0] for k, v in parse_qs(urlparse(resp.headers["location"]).fragment).items()}


def test_oauth_signup_without_approval_is_refused(oauth, app_client):
    from app.models.models import User

    _request(app_client)  # pending is not approved
    assert _google(app_client) == {"error": "not_approved"}
    with _db() as db:
        assert db.scalar(select(User).where(User.email == "jane@example.com")) is None


def test_oauth_signup_with_approved_request_works_once(oauth, app_client, waitlist, monkeypatch):
    admin = _platform_admin(app_client, waitlist, monkeypatch)
    monkeypatch.setattr(waitlist, "signup_mode", "waitlist")
    _request(app_client)
    token = _approve(app_client, admin)
    assert "token" in _google(app_client)
    assert "token" in _google(app_client)  # existing account: signs straight in
    assert app_client.get(f"/auth/access/{token}").status_code == 410  # emailed link is spent


def test_oauth_invite_still_works_in_waitlist_mode(oauth, app_client, waitlist, monkeypatch):
    monkeypatch.setattr(waitlist, "signup_mode", "open")
    owner = _headers(_signup(app_client, "owner@acme.com"))
    app_client.post("/org/invites", json={"email": "jane@example.com", "role": "VIEWER"}, headers=owner)
    monkeypatch.setattr(waitlist, "signup_mode", "waitlist")
    result = _google(app_client)
    me = app_client.get("/me", headers={"Authorization": f"Bearer {result['token']}"}).json()
    assert me["role"] == "VIEWER"


def test_existing_oauth_user_signs_in_in_waitlist_mode(oauth, app_client, waitlist, monkeypatch):
    monkeypatch.setattr(waitlist, "signup_mode", "open")
    first = _google(app_client)
    monkeypatch.setattr(waitlist, "signup_mode", "waitlist")
    again = _google(app_client)
    assert "token" in first and "token" in again
