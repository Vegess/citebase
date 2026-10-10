"""Sprint 6: sessions that survive a refresh, password reset, account settings,
connected providers, Word/Markdown uploads, samples, passages, home page."""
import io
import zipfile
from urllib.parse import parse_qs, urlparse

import pytest

PASSWORD = "password123"
XRW = {"X-Requested-With": "citebase"}


def _signup(client, email="o@acme.com", org="Acme"):
    token = client.post("/auth/signup", json={"email": email, "password": PASSWORD, "org_name": org}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _login(client, email, password=PASSWORD):
    return client.post("/auth/login", data={"username": email, "password": password})


def _invite_and_join(client, owner_h, email, role="MEMBER"):
    token = client.post("/org/invites", headers=owner_h, json={"email": email, "role": role}).json()["token"]
    access = client.post("/auth/accept-invite", json={"token": token, "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {access}"}


@pytest.fixture()
def cookie_root(app_client, monkeypatch):
    # In production the browser sees these endpoints under /api/auth (Vercel
    # proxy); the test client talks to the API directly.
    from app.routes import account
    monkeypatch.setattr(account.settings, "session_cookie_path", "/")
    return app_client


# ---- Sessions ----

def test_session_cookie_survives_a_refresh_and_ends_on_logout(cookie_root):
    client = cookie_root
    h = _signup(client)
    assert client.post("/auth/session", headers=h).status_code == 403  # no CSRF header
    resp = client.post("/auth/session", headers={**h, **XRW})
    assert resp.status_code == 204
    set_cookie = resp.headers["set-cookie"].lower()
    assert "citebase_session=" in set_cookie and "httponly" in set_cookie and "samesite=lax" in set_cookie

    # "Refresh the page": only the cookie is left.
    fresh = client.post("/auth/refresh", headers=XRW)
    assert fresh.status_code == 200
    assert client.get("/me", headers={"Authorization": f"Bearer {fresh.json()['access_token']}"}).status_code == 200
    assert client.post("/auth/refresh").status_code == 403  # header still required

    assert client.post("/auth/logout", headers=XRW).status_code == 204
    assert client.post("/auth/refresh", headers=XRW).status_code == 401


def test_removed_member_cannot_refresh(cookie_root):
    client = cookie_root
    owner = _signup(client)
    member = _invite_and_join(client, owner, "m@acme.com")
    client.cookies.clear()
    client.post("/auth/session", headers={**member, **XRW})
    member_id = client.get("/me", headers=member).json()["id"]
    client.delete(f"/org/members/{member_id}", headers=owner)
    assert client.post("/auth/refresh", headers=XRW).status_code == 401


def test_stored_session_is_only_a_hash(cookie_root):
    import app.core.database as database
    from app.models.models import UserSession

    client = cookie_root
    h = _signup(client)
    client.post("/auth/session", headers={**h, **XRW})
    raw = client.cookies.get("citebase_session")
    with database.SessionLocal() as db:
        stored = db.query(UserSession).one()
        assert stored.token_hash != raw and len(stored.token_hash) == 64


# ---- Password change / sign out everywhere ----

def test_password_change_needs_current_password_and_signs_out_other_devices(cookie_root):
    client = cookie_root
    h = _signup(client)
    client.post("/auth/session", headers={**h, **XRW})
    bad = client.post("/account/password", headers=h, json={"current_password": "wrong", "new_password": "newpass123"})
    assert bad.status_code == 400
    ok = client.post("/account/password", headers=h, json={"current_password": PASSWORD, "new_password": "newpass123"})
    assert ok.status_code == 200
    assert client.get("/me", headers=h).status_code == 401  # old token is dead
    assert client.get("/me", headers={"Authorization": f"Bearer {ok.json()['access_token']}"}).status_code == 200
    assert client.post("/auth/refresh", headers=XRW).status_code == 401  # old session is dead
    assert _login(client, "o@acme.com").status_code == 401
    assert _login(client, "o@acme.com", "newpass123").status_code == 200


def test_sign_out_everywhere_kills_existing_tokens(app_client):
    h = _signup(app_client)
    assert app_client.post("/account/sign-out-everywhere", headers=h).status_code == 204
    assert app_client.get("/me", headers=h).status_code == 401


# ---- Password reset ----

def test_forgot_password_without_email_gives_the_same_answer(app_client):
    _signup(app_client)
    a = app_client.post("/auth/forgot-password", json={"email": "o@acme.com"})
    b = app_client.post("/auth/forgot-password", json={"email": "nobody@acme.com"})
    assert a.status_code == b.status_code == 202 and a.json() == b.json() == {"email_enabled": False}


def test_emailed_reset_link_works_once_and_verifies_the_email(app_client, monkeypatch):
    from app.services import mailer

    sent = []
    monkeypatch.setattr(mailer, "enabled", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda to, subject, text: sent.append((to, text)) or True)
    h = _signup(app_client)
    sent.clear()  # sign-up sends a confirmation email; only reset emails matter here
    assert app_client.post("/auth/forgot-password", json={"email": "nobody@acme.com"}).status_code == 202
    assert sent == []  # unknown email: nothing sent, same response
    app_client.post("/auth/forgot-password", json={"email": "O@acme.com"})
    to, text = sent[0]
    token = text.split("/reset-password#", 1)[1].split()[0]
    assert to == "o@acme.com"
    assert app_client.get(f"/auth/password-reset/{token}").json() == {"email": "o@acme.com"}

    done = app_client.post("/auth/password-reset", json={"token": token, "password": "brandnew99"})
    assert done.status_code == 200
    assert app_client.post("/auth/password-reset", json={"token": token, "password": "again12345"}).status_code == 400
    assert app_client.get("/me", headers=h).status_code == 401
    assert _login(app_client, "o@acme.com", "brandnew99").status_code == 200
    account = app_client.get("/account", headers={"Authorization": f"Bearer {done.json()['access_token']}"}).json()
    assert account["email_verified"] is True


def test_admin_reset_links_follow_the_role_rules(app_client):
    owner = _signup(app_client)
    admin = _invite_and_join(app_client, owner, "a@acme.com", "ADMIN")
    member = _invite_and_join(app_client, owner, "m@acme.com")
    ids = {m["email"]: m["id"] for m in app_client.get("/org/members", headers=owner).json()}

    link = app_client.post(f"/org/members/{ids['m@acme.com']}/reset-link", headers=admin)
    assert link.status_code == 201
    token = link.json()["url"].split("#", 1)[1]
    assert app_client.post(f"/org/members/{ids['o@acme.com']}/reset-link", headers=admin).status_code == 403
    assert app_client.post(f"/org/members/{ids['a@acme.com']}/reset-link", headers=member).status_code == 403

    app_client.post("/auth/password-reset", json={"token": token, "password": "memberpw99"})
    assert _login(app_client, "m@acme.com", "memberpw99").status_code == 200
    actions = [e["action"] for e in app_client.get("/org/audit", headers=owner).json()]
    assert "member.reset_link_created" in actions and "account.password_reset" in actions


def test_admin_reset_does_not_verify_the_email(app_client):
    owner = _signup(app_client)
    _invite_and_join(app_client, owner, "m@acme.com")
    mid = next(m["id"] for m in app_client.get("/org/members", headers=owner).json() if m["email"] == "m@acme.com")
    token = app_client.post(f"/org/members/{mid}/reset-link", headers=owner).json()["url"].split("#", 1)[1]
    access = app_client.post("/auth/password-reset", json={"token": token, "password": "memberpw99"}).json()["access_token"]
    assert app_client.get("/account", headers={"Authorization": f"Bearer {access}"}).json()["email_verified"] is False


# ---- Connected providers ----

@pytest.fixture()
def github(app_client, monkeypatch):
    from app.routes import oauth as oauth_module

    s = oauth_module.settings
    monkeypatch.setattr(s, "github_client_id", "gh")
    monkeypatch.setattr(s, "github_client_secret", "ghs")
    monkeypatch.setattr(s, "api_public_url", "https://api.example.com")
    monkeypatch.setattr(s, "frontend_url", "https://app.example.com")
    monkeypatch.setattr(oauth_module, "_exchange_code", lambda provider, code: "tok")
    identity = {"email": "o@acme.com"}
    monkeypatch.setattr(oauth_module, "fetch_verified_email", lambda p, t: (identity["email"], "Owner"))
    return identity


def _run_oauth(client, start_url):
    path = start_url.replace("https://api.example.com", "")
    resp = client.get(path, follow_redirects=False)
    state = parse_qs(urlparse(resp.headers["location"]).query)["state"][0]
    nonce = resp.cookies.get("citebase_oauth_nonce")
    client.cookies.clear()
    client.cookies.set("citebase_oauth_nonce", nonce, path="/auth/oauth")
    done = client.get(f"/auth/oauth/github/callback?code=c&state={state}", follow_redirects=False)
    return urlparse(done.headers["location"])


def test_connecting_github_to_a_password_account_then_signing_in_with_it(github, app_client):
    h = _signup(app_client)
    url = app_client.post("/account/link/github", headers=h).json()["url"]
    back = _run_oauth(app_client, url)
    assert back.path == "/settings" and parse_qs(back.fragment) == {"linked": ["github"]}
    account = app_client.get("/account", headers=h).json()
    assert account["email_verified"] and account["identities"] == [{"provider": "github", "email": "o@acme.com"}]

    # Now GitHub sign-in enters the same account.
    signin = _run_oauth(app_client, "/auth/oauth/github/start")
    token = parse_qs(signin.fragment)["token"][0]
    assert app_client.get("/me", headers={"Authorization": f"Bearer {token}"}).json()["org_name"] == "Acme"


def test_connecting_a_github_with_a_different_email_is_refused(github, app_client):
    h = _signup(app_client)
    github["email"] = "someone.else@gmail.com"
    back = _run_oauth(app_client, app_client.post("/account/link/github", headers=h).json()["url"])
    assert back.path == "/settings" and parse_qs(back.fragment) == {"error": ["email_mismatch"]}
    assert app_client.get("/account", headers=h).json()["identities"] == []


def test_cannot_remove_the_only_way_to_sign_in(github, app_client):
    signin = _run_oauth(app_client, "/auth/oauth/github/start")
    h = {"Authorization": f"Bearer {parse_qs(signin.fragment)['token'][0]}"}
    assert app_client.get("/account", headers=h).json()["password_set"] is False
    assert app_client.delete("/account/identities/github", headers=h).status_code == 400
    # Setting a password needs no current password for provider-only accounts.
    new = app_client.post("/account/password", headers=h, json={"new_password": "nowiknow1"}).json()["access_token"]
    h = {"Authorization": f"Bearer {new}"}
    assert app_client.delete("/account/identities/github", headers=h).status_code == 204


# ---- Uploads ----

def _docx(paragraphs):
    body = "".join(paragraphs)
    xml = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
           f'wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def _p(text, style=None):
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def test_word_document_keeps_headings_and_tables():
    from app.services import extract

    table = ("<w:tbl><w:tr><w:tc>" + _p("Grade") + "</w:tc><w:tc>" + _p("Days") + "</w:tc></w:tr>"
             "<w:tr><w:tc>" + _p("Senior") + "</w:tc><w:tc>" + _p("25") + "</w:tc></w:tr></w:tbl>")
    raw = _docx([_p("Leave Policy", "Heading1"), _p("Staff get annual leave."), table])
    text = extract.extract(raw, "policy.docx")
    assert "## Leave Policy" in text and "Staff get annual leave." in text and "Senior | 25" in text


def test_docx_and_markdown_uploads_are_accepted(app_client):
    h = _signup(app_client)
    docx = app_client.post("/documents", headers=h, files={"file": (
        "Leave.docx", io.BytesIO(_docx([_p("Notice is 30 days.")])),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    md = app_client.post("/documents", headers=h, files={"file": (
        "travel.md", io.BytesIO(b"# Travel\n\nBook via the [portal](https://x.example)."), "text/markdown")})
    assert docx.status_code == 201 and md.status_code == 201
    junk = app_client.post("/documents", headers=h, files={"file": ("x.bin", io.BytesIO(b"\x00\xff\xfe" * 10),
                                                                     "application/octet-stream")})
    assert junk.status_code == 415


def test_broken_word_file_is_rejected_clearly(app_client):
    h = _signup(app_client)
    resp = app_client.post("/documents", headers=h, files={"file": ("bad.docx", io.BytesIO(b"PK\x03\x04garbage"),
                                                                    "application/octet-stream")})
    assert resp.status_code == 422 and "damaged" in resp.json()["detail"]


def test_sample_documents_load_once(app_client):
    h = _signup(app_client)
    first = app_client.post("/documents/samples", headers=h)
    assert first.status_code == 201 and len(first.json()) == 5
    assert app_client.post("/documents/samples", headers=h).json() == []
    assert len(app_client.get("/documents", headers=h).json()) == 5


# ---- Passages ----

def test_passage_behind_a_citation_is_workspace_scoped(app_client):
    a = _signup(app_client)
    b = _signup(app_client, "b@beta.com", "Beta")
    app_client.post("/documents", headers=a, files={"file": ("h.txt", io.BytesIO(b"Notice is 30 days."), "text/plain")})
    answer = app_client.post("/chat/ask", headers=a, json={"question": "notice?"}).json()
    cite = answer["citations"][0]
    passage = app_client.get("/documents/passage", headers=a, params={"doc_id": cite["doc_id"], "chunk_index": cite["chunk_index"]})
    assert passage.status_code == 200 and "30 days" in passage.json()["text"]
    by_name = app_client.get("/documents/passage", headers=a, params={"filename": "h.txt", "chunk_index": 0})
    assert by_name.json()["doc_id"] == cite["doc_id"]
    other = app_client.get("/documents/passage", headers=b, params={"doc_id": cite["doc_id"], "chunk_index": 0})
    assert other.status_code == 404


# ---- Home and workspace ----

def test_home_checklist_and_privacy_of_questions(app_client):
    owner = _signup(app_client)
    home = app_client.get("/home", headers=owner).json()
    assert home["checklist"] == {"has_documents": False, "has_asked": False, "has_teammates": False}
    app_client.post("/documents", headers=owner, files={"file": ("h.txt", io.BytesIO(b"Notice is 30 days."), "text/plain")})
    app_client.post("/chat/ask", headers=owner, json={"question": "notice?"})
    member = _invite_and_join(app_client, owner, "m@acme.com")
    home = app_client.get("/home", headers=owner).json()
    assert home["checklist"] == {"has_documents": True, "has_asked": True, "has_teammates": True}
    assert home["popular_questions"][0]["question"] == "notice?"
    assert app_client.get("/home", headers=member).json()["popular_questions"] == []


def test_admins_can_rename_the_workspace(app_client):
    owner = _signup(app_client)
    member = _invite_and_join(app_client, owner, "m@acme.com")
    assert app_client.patch("/org", headers=member, json={"name": "X"}).status_code == 403
    assert app_client.patch("/org", headers=owner, json={"name": "A"}).status_code == 400
    assert app_client.patch("/org", headers=owner, json={"name": "Acme Insurance"}).json() == {"name": "Acme Insurance"}
    assert app_client.get("/me", headers=owner).json()["org_name"] == "Acme Insurance"
