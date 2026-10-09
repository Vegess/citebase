"""Sprint 4b: Google/GitHub sign-in and workspace deletion."""
import io
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import func, select

PASSWORD = "password123"


@pytest.fixture()
def oauth(app_client, monkeypatch):
    from app.routes import oauth as oauth_module

    s = oauth_module.settings
    monkeypatch.setattr(s, "google_client_id", "gid")
    monkeypatch.setattr(s, "google_client_secret", "gsecret")
    monkeypatch.setattr(s, "github_client_id", None)
    monkeypatch.setattr(s, "api_public_url", "https://api.example.com")
    monkeypatch.setattr(s, "frontend_url", "https://app.example.com")
    monkeypatch.setattr(oauth_module, "_exchange_code", lambda provider, code: f"access-{code}")
    identity = {"email": "New.Person@Gmail.com", "name": "New Person"}
    monkeypatch.setattr(oauth_module, "fetch_verified_email",
                        lambda provider, token: (identity["email"], identity["name"]))
    return oauth_module, identity


def _start(client):
    resp = client.get("/auth/oauth/google/start", follow_redirects=False)
    assert resp.status_code == 302
    query = parse_qs(urlparse(resp.headers["location"]).query)
    return query["state"][0], resp.cookies.get("documind_oauth_nonce")


def _finish(client, state, nonce, code="abc"):
    client.cookies.clear()
    if nonce:
        client.cookies.set("documind_oauth_nonce", nonce, path="/auth/oauth")
    resp = client.get(f"/auth/oauth/google/callback?code={code}&state={state}", follow_redirects=False)
    assert resp.status_code == 302
    fragment = parse_qs(urlparse(resp.headers["location"]).fragment)
    return {k: v[0] for k, v in fragment.items()}


def test_providers_lists_only_configured_ones(oauth, app_client):
    assert app_client.get("/auth/providers").json() == {"providers": ["google"]}
    assert app_client.get("/auth/oauth/github/start", follow_redirects=False).status_code == 404


def test_start_redirects_to_google_with_signed_state(oauth, app_client):
    resp = app_client.get("/auth/oauth/google/start", follow_redirects=False)
    url = urlparse(resp.headers["location"])
    q = parse_qs(url.query)
    assert url.netloc == "accounts.google.com"
    assert q["redirect_uri"] == ["https://api.example.com/auth/oauth/google/callback"]
    assert q["client_id"] == ["gid"] and "email" in q["scope"][0]
    assert "httponly" in resp.headers["set-cookie"].lower()


def test_first_sign_in_creates_a_new_workspace(oauth, app_client):
    state, nonce = _start(app_client)
    result = _finish(app_client, state, nonce)
    headers = {"Authorization": f"Bearer {result['token']}"}
    me = app_client.get("/me", headers=headers).json()
    assert me["email"] == "new.person@gmail.com" and me["role"] == "OWNER"
    assert me["org_name"] == "New Person's workspace"

    # Signing in again logs into the same account, no second workspace.
    state, nonce = _start(app_client)
    again = _finish(app_client, state, nonce)
    assert app_client.get("/me", headers={"Authorization": f"Bearer {again['token']}"}).json()["id"] == me["id"]


def test_password_account_cannot_be_claimed_through_google(oauth, app_client):
    """Account pre-hijacking: someone registers the victim's email with a
    password and invites a second account of their own. Google sign-in must
    not log the real owner into that workspace."""
    _, identity = oauth
    attacker = app_client.post("/auth/signup", json={"email": "victim@corp.com", "password": PASSWORD,
                                                     "org_name": "Trap"}).json()["access_token"]
    app_client.post("/org/invites", headers={"Authorization": f"Bearer {attacker}"},
                    json={"email": "spy@evil.com", "role": "ADMIN"})
    identity["email"] = "Victim@Corp.com"
    state, nonce = _start(app_client)
    assert _finish(app_client, state, nonce) == {"error": "use_password"}

    # The password still works for whoever set it; nothing new was created.
    assert app_client.post("/auth/login", data={"username": "victim@corp.com", "password": PASSWORD}).status_code == 200


def test_google_and_github_share_a_provider_created_account(oauth, app_client):
    oauth_module, _ = oauth
    state, nonce = _start(app_client)
    first = _finish(app_client, state, nonce)["token"]
    me = app_client.get("/me", headers={"Authorization": f"Bearer {first}"}).json()
    import app.core.database as database
    with database.SessionLocal() as db:
        user = oauth_module.sign_in_with_email(db, "github", "new.person@gmail.com", None)
        assert user.id == me["id"]


def test_open_invite_is_honoured_on_first_sign_in(oauth, app_client):
    _, identity = oauth
    owner = app_client.post("/auth/signup", json={"email": "o@acme.com", "password": PASSWORD,
                                                  "org_name": "Acme"}).json()["access_token"]
    owner_h = {"Authorization": f"Bearer {owner}"}
    app_client.post("/org/invites", headers=owner_h, json={"email": "hire@acme.com", "role": "VIEWER"})
    identity["email"] = "hire@acme.com"
    state, nonce = _start(app_client)
    token = _finish(app_client, state, nonce)["token"]
    me = app_client.get("/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["org_name"] == "Acme" and me["role"] == "VIEWER"
    assert app_client.get("/org/invites", headers=owner_h).json() == []  # invite used up


@pytest.mark.parametrize("tamper,reason", [
    ("missing_cookie", "state_mismatch"),
    ("wrong_cookie", "state_mismatch"),
    ("bad_state", "expired"),
])
def test_callback_rejects_forged_or_replayed_state(oauth, app_client, tamper, reason):
    state, nonce = _start(app_client)
    if tamper == "missing_cookie":
        nonce = None
    elif tamper == "wrong_cookie":
        nonce = "attacker-nonce"
    else:
        state = state[:-4] + "AAAA"
    result = _finish(app_client, state, nonce)
    assert result == {"error": reason}


def test_unverified_email_is_refused(oauth, app_client, monkeypatch):
    oauth_module, _ = oauth

    def unverified(provider, token):
        raise ValueError("no verified email")

    monkeypatch.setattr(oauth_module, "fetch_verified_email", unverified)
    state, nonce = _start(app_client)
    assert _finish(app_client, state, nonce) == {"error": "no_verified_email"}


def test_oauth_accounts_cannot_log_in_with_a_guessed_password(oauth, app_client):
    state, nonce = _start(app_client)
    _finish(app_client, state, nonce)
    resp = app_client.post("/auth/login", data={"username": "new.person@gmail.com", "password": "password123"})
    assert resp.status_code == 401


# ---- Delete workspace ----

def test_owner_can_delete_the_workspace_and_everything_in_it(app_client):
    import app.core.database as database
    from app.models.models import Document, DocumentChunk, Org, User

    owner = {"Authorization": "Bearer " + app_client.post("/auth/signup", json={
        "email": "o@acme.com", "password": PASSWORD, "org_name": "Acme"}).json()["access_token"]}
    other = {"Authorization": "Bearer " + app_client.post("/auth/signup", json={
        "email": "b@beta.com", "password": PASSWORD, "org_name": "Beta"}).json()["access_token"]}
    for h in (owner, other):
        app_client.post("/documents", headers=h, files={"file": ("a.txt", io.BytesIO(b"Notice is 30 days."), "text/plain")})
        app_client.post("/chat/ask", headers=h, json={"question": "notice?"})

    assert app_client.request("DELETE", "/org", headers=owner, json={"confirm_name": "acme"}).status_code == 400
    assert app_client.request("DELETE", "/org", headers=owner, json={"confirm_name": "Acme"}).status_code == 204

    assert app_client.get("/me", headers=owner).status_code == 401
    with database.SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Org).where(Org.name == "Acme")) == 0
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert db.scalar(select(func.count()).select_from(Document)) == 1
        assert db.scalar(select(func.count()).select_from(DocumentChunk)) >= 1
    assert len(app_client.get("/documents", headers=other).json()) == 1  # other workspace untouched


def test_only_the_owner_can_delete_the_workspace(app_client):
    owner = {"Authorization": "Bearer " + app_client.post("/auth/signup", json={
        "email": "o@acme.com", "password": PASSWORD, "org_name": "Acme"}).json()["access_token"]}
    token = app_client.post("/org/invites", headers=owner, json={"email": "a@acme.com", "role": "ADMIN"}).json()["token"]
    admin = {"Authorization": "Bearer " + app_client.post("/auth/accept-invite", json={
        "token": token, "password": PASSWORD}).json()["access_token"]}
    assert app_client.request("DELETE", "/org", headers=admin, json={"confirm_name": "Acme"}).status_code == 403
