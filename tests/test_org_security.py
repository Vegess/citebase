"""Sprint 1: tenant isolation at signup, roles, single-use invites, audit log."""
import io
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

PASSWORD = "password123"


def signup(client, email, org_name="Acme"):
    resp = client.post("/auth/signup", json={"email": email, "password": PASSWORD, "org_name": org_name})
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def me(client, headers):
    return client.get("/me", headers=headers).json()


def upload(client, headers, name="handbook.txt", body=b"Notice period is 30 days."):
    return client.post("/documents", headers=headers, files={"file": (name, io.BytesIO(body), "text/plain")})


def invite(client, headers, email, role="MEMBER"):
    return client.post("/org/invites", headers=headers, json={"email": email, "role": role})


def accept(client, token, password=PASSWORD):
    return client.post("/auth/accept-invite", json={"token": token, "password": password})


def join(client, admin_headers, email, role="MEMBER"):
    created = invite(client, admin_headers, email, role)
    assert created.status_code == 201, created.text
    resp = accept(client, created.json()["token"])
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ---- The original vulnerability ----

def test_signup_with_existing_org_name_creates_a_separate_org(app_client):
    victim = signup(app_client, "victim@corp.com", org_name="Atribs Pvt. Limited")
    assert upload(app_client, victim, "salaries.txt", b"CEO salary is confidential.").status_code == 201
    time.sleep(0.2)

    attacker = signup(app_client, "attacker@evil.com", org_name="Atribs Pvt. Limited")

    assert me(app_client, attacker)["org_id"] != me(app_client, victim)["org_id"]
    assert me(app_client, attacker)["role"] == "OWNER"
    assert app_client.get("/documents", headers=attacker).json() == []
    answer = app_client.post("/chat/ask", headers=attacker, json={"question": "salary"}).json()
    assert answer["citations"] == []


def test_signup_owner_role_and_case_insensitive_email(app_client):
    signup(app_client, "Mixed.Case@Example.com")
    assert app_client.post("/auth/signup", json={
        "email": "mixed.case@example.com", "password": PASSWORD, "org_name": "Other"}).status_code == 409
    login = app_client.post("/auth/login", data={"username": "MIXED.CASE@example.com", "password": PASSWORD})
    assert login.status_code == 200


# ---- Invites ----

def test_invite_flow_joins_the_inviters_org(app_client):
    owner = signup(app_client, "owner@acme.com")
    created = invite(app_client, owner, "New.Hire@Acme.com", "MEMBER").json()
    assert created["email"] == "new.hire@acme.com"

    preview = app_client.get(f"/auth/invites/{created['token']}")
    assert preview.status_code == 200
    assert preview.json() == {"org_name": "Acme", "email": "new.hire@acme.com", "role": "MEMBER"}

    resp = accept(app_client, created["token"])
    assert resp.status_code == 201
    member = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    assert me(app_client, member)["org_id"] == me(app_client, owner)["org_id"]
    assert me(app_client, member)["role"] == "MEMBER"


def test_invite_is_single_use(app_client):
    owner = signup(app_client, "owner@acme.com")
    token = invite(app_client, owner, "a@acme.com").json()["token"]
    assert accept(app_client, token).status_code == 201
    assert accept(app_client, token).status_code == 410
    assert app_client.get(f"/auth/invites/{token}").status_code == 410


def test_concurrent_accepts_create_exactly_one_account(app_client):
    owner = signup(app_client, "owner@acme.com")
    token = invite(app_client, owner, "race@acme.com").json()["token"]

    with ThreadPoolExecutor(max_workers=5) as pool:
        codes = list(pool.map(lambda _: accept(app_client, token).status_code, range(5)))

    assert codes.count(201) == 1, codes
    assert set(codes) - {201} <= {409, 410}, codes  # losers get a clean error, never a 500
    members = app_client.get("/org/members", headers=owner).json()
    assert [m["email"] for m in members].count("race@acme.com") == 1


def test_revoked_and_expired_invites_are_rejected(app_client):
    import app.core.database as database
    from app.models.models import OrgInvite

    owner = signup(app_client, "owner@acme.com")
    revoked = invite(app_client, owner, "r@acme.com").json()
    assert app_client.delete(f"/org/invites/{revoked['id']}", headers=owner).status_code == 204
    assert accept(app_client, revoked["token"]).status_code == 410

    expired = invite(app_client, owner, "e@acme.com").json()
    with database.SessionLocal() as db:
        row = db.get(OrgInvite, expired["id"])
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    assert accept(app_client, expired["token"]).status_code == 410


def test_reinviting_replaces_the_old_link(app_client):
    owner = signup(app_client, "owner@acme.com")
    first = invite(app_client, owner, "x@acme.com").json()["token"]
    second = invite(app_client, owner, "x@acme.com").json()["token"]
    assert accept(app_client, first).status_code == 410
    assert accept(app_client, second).status_code == 201


def test_cannot_invite_existing_account(app_client):
    owner = signup(app_client, "owner@acme.com")
    signup(app_client, "taken@other.com", org_name="Other")
    assert invite(app_client, owner, "TAKEN@other.com").status_code == 409


# ---- Roles ----

def test_role_permissions_on_documents(app_client):
    owner = signup(app_client, "owner@acme.com")
    member = join(app_client, owner, "m@acme.com", "MEMBER")
    viewer = join(app_client, owner, "v@acme.com", "VIEWER")

    assert upload(app_client, viewer).status_code == 403
    owner_doc = upload(app_client, owner, "owner.txt").json()
    member_doc = upload(app_client, member, "member.txt").json()
    time.sleep(0.2)

    assert len(app_client.get("/documents", headers=viewer).json()) == 2
    assert app_client.post("/chat/ask", headers=viewer, json={"question": "notice"}).status_code == 200

    assert app_client.delete(f"/documents/{owner_doc['id']}", headers=member).status_code == 403
    assert app_client.delete(f"/documents/{member_doc['id']}", headers=member).status_code == 204
    assert app_client.delete(f"/documents/{owner_doc['id']}", headers=owner).status_code == 204


def test_only_admins_reach_org_admin_routes(app_client):
    owner = signup(app_client, "owner@acme.com")
    member = join(app_client, owner, "m@acme.com", "MEMBER")
    for method, path in [("get", "/org/members"), ("get", "/org/invites"), ("get", "/org/audit")]:
        assert getattr(app_client, method)(path, headers=member).status_code == 403
    assert invite(app_client, member, "z@acme.com").status_code == 403


def test_role_grant_rules(app_client):
    owner = signup(app_client, "owner@acme.com")
    admin = join(app_client, owner, "admin@acme.com", "ADMIN")
    member = join(app_client, owner, "m@acme.com", "MEMBER")
    owner_id, admin_id, member_id = (me(app_client, h)["id"] for h in (owner, admin, member))

    # Admin cannot mint other admins, promote to admin, or touch the owner.
    assert invite(app_client, admin, "a2@acme.com", "ADMIN").status_code == 403
    assert app_client.patch(f"/org/members/{member_id}", headers=admin, json={"role": "ADMIN"}).status_code == 403
    assert app_client.patch(f"/org/members/{owner_id}", headers=admin, json={"role": "VIEWER"}).status_code == 403
    # OWNER is never assignable through the API.
    assert app_client.patch(f"/org/members/{member_id}", headers=owner, json={"role": "OWNER"}).status_code == 422
    # Nobody edits themselves.
    assert app_client.patch(f"/org/members/{admin_id}", headers=admin, json={"role": "MEMBER"}).status_code == 400

    resp = app_client.patch(f"/org/members/{member_id}", headers=admin, json={"role": "VIEWER"})
    assert resp.status_code == 200 and resp.json()["role"] == "VIEWER"
    assert upload(app_client, member).status_code == 403  # demotion takes effect on the next request


def test_removed_member_loses_access_immediately(app_client):
    owner = signup(app_client, "owner@acme.com")
    member = join(app_client, owner, "m@acme.com")
    member_id = me(app_client, member)["id"]

    assert app_client.delete(f"/org/members/{member_id}", headers=owner).status_code == 204
    assert app_client.get("/documents", headers=member).status_code == 401
    assert app_client.post("/auth/login", data={"username": "m@acme.com", "password": PASSWORD}).status_code == 401


def test_members_are_scoped_to_their_org(app_client):
    owner_a = signup(app_client, "a@a.com", org_name="OrgA")
    owner_b = signup(app_client, "b@b.com", org_name="OrgB")
    member_b = join(app_client, owner_b, "m@b.com")
    member_b_id = me(app_client, member_b)["id"]

    assert [m["email"] for m in app_client.get("/org/members", headers=owner_a).json()] == ["a@a.com"]
    assert app_client.delete(f"/org/members/{member_b_id}", headers=owner_a).status_code == 404


def test_audit_log_records_security_events(app_client):
    owner = signup(app_client, "owner@acme.com")
    member = join(app_client, owner, "m@acme.com")
    upload(app_client, member)
    member_id = me(app_client, member)["id"]
    app_client.patch(f"/org/members/{member_id}", headers=owner, json={"role": "VIEWER"})

    actions = [e["action"] for e in app_client.get("/org/audit", headers=owner).json()]
    for expected in ("org.created", "invite.created", "invite.accepted", "document.uploaded", "member.role_changed"):
        assert expected in actions, actions
