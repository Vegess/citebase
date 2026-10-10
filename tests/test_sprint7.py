"""Sprint 7: collections with access control, document versions, verified
answers, conflict review, document detail."""
import io
import json

PASSWORD = "password123"


def _signup(client, email="o@acme.com", org="Acme"):
    token = client.post("/auth/signup", json={"email": email, "password": PASSWORD, "org_name": org}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _join(client, owner_h, email, role="MEMBER"):
    token = client.post("/org/invites", headers=owner_h, json={"email": email, "role": role}).json()["token"]
    access = client.post("/auth/accept-invite", json={"token": token, "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {access}"}


def _upload(client, h, name, text, collection_id=None):
    data = {"collection_id": collection_id} if collection_id else None
    resp = client.post("/documents", headers=h, data=data, files={"file": (name, io.BytesIO(text.encode()), "text/plain")})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _me(client, h):
    return client.get("/me", headers=h).json()["id"]


def _setup_hr(client):
    owner = _signup(client)
    hr = _join(client, owner, "hr@acme.com")
    staff = _join(client, owner, "staff@acme.com")
    col = client.post("/collections", headers=owner, json={
        "name": "HR private", "restricted": True, "member_ids": [_me(client, hr)]}).json()
    salary = _upload(client, owner, "salaries.txt", "Salary bands: grade A earns 90000 rupees per month.", col["id"])
    handbook = _upload(client, owner, "handbook.txt", "The notice period is 30 days for all staff.")
    return owner, hr, staff, col, salary, handbook


# ---- Collections and access ----

def test_restricted_documents_are_invisible_to_non_members_everywhere(app_client):
    owner, hr, staff, col, salary, handbook = _setup_hr(app_client)

    names = lambda h: {d["filename"] for d in app_client.get("/documents", headers=h).json()}
    assert names(owner) == {"salaries.txt", "handbook.txt"}
    assert names(hr) == {"salaries.txt", "handbook.txt"}
    assert names(staff) == {"handbook.txt"}

    assert app_client.get(f"/documents/{salary['id']}", headers=staff).status_code == 404
    assert app_client.get(f"/documents/{salary['id']}/detail", headers=staff).status_code == 404
    assert app_client.get("/documents/passage", headers=staff,
                          params={"doc_id": salary["id"], "chunk_index": 0}).status_code == 404
    assert app_client.get("/documents/passage", headers=staff,
                          params={"filename": "salaries.txt", "chunk_index": 0}).status_code == 404
    assert app_client.delete(f"/documents/{salary['id']}", headers=staff).status_code == 404

    # Search never returns the restricted passage to staff, even when asked directly.
    for h, should_see in ((staff, False), (hr, True), (owner, True)):
        answer = app_client.post("/chat/ask", headers=h, json={"question": "What are the salary bands for grade A?"}).json()
        cited = {c["filename"] for c in answer["citations"]}
        assert ("salaries.txt" in cited) is should_see, (h, cited)

    home = app_client.get("/home", headers=staff).json()
    assert [d["filename"] for d in home["recent_documents"]] == ["handbook.txt"]
    cols = app_client.get("/collections", headers=staff).json()["collections"]
    assert cols == []
    assert [c["name"] for c in app_client.get("/collections", headers=hr).json()["collections"]] == ["HR private"]


def test_non_members_cannot_upload_into_or_manage_restricted_collections(app_client):
    owner, hr, staff, col, *_ = _setup_hr(app_client)
    resp = app_client.post("/documents", headers=staff, data={"collection_id": col["id"]},
                           files={"file": ("x.txt", io.BytesIO(b"hello"), "text/plain")})
    assert resp.status_code == 404
    assert app_client.post("/collections", headers=hr, json={"name": "Mine"}).status_code == 403
    assert app_client.patch(f"/collections/{col['id']}", headers=hr, json={"restricted": False}).status_code == 403


def test_open_collections_are_visible_to_everyone(app_client):
    owner = _signup(app_client)
    staff = _join(app_client, owner, "staff@acme.com")
    _ = app_client.post("/collections", headers=owner, json={"name": "Restricted", "restricted": True}).json()
    legal = app_client.post("/collections", headers=owner, json={"name": "Legal"}).json()
    _upload(app_client, owner, "nda.txt", "NDAs last two years.", legal["id"])
    assert {d["filename"] for d in app_client.get("/documents", headers=staff).json()} == {"nda.txt"}


def test_moving_a_document_changes_who_can_see_it(app_client):
    owner, hr, staff, col, salary, handbook = _setup_hr(app_client)
    moved = app_client.patch(f"/documents/{handbook['id']}", headers=owner, json={"collection_id": col["id"]})
    assert moved.status_code == 200 and moved.json()["collection_id"] == col["id"]
    assert app_client.get("/documents", headers=staff).json() == []
    # Members can't move someone else's document.
    assert app_client.patch(f"/documents/{handbook['id']}", headers=hr, json={"collection_id": None}).status_code == 403


def test_a_collection_with_documents_cannot_be_deleted(app_client):
    owner, hr, staff, col, salary, _ = _setup_hr(app_client)
    assert app_client.delete(f"/collections/{col['id']}", headers=owner).status_code == 409
    app_client.delete(f"/documents/{salary['id']}", headers=owner)
    assert app_client.delete(f"/collections/{col['id']}", headers=owner).status_code == 204


def test_conflict_checker_never_quotes_a_restricted_document_on_a_general_one(app_client, monkeypatch):
    import app.core.database as database
    from app.models.models import Document
    from app.services import conflicts

    owner, hr, staff, col, salary, handbook = _setup_hr(app_client)
    _upload(app_client, owner, "benefits.txt", "Staff get health insurance and a notice period bonus.")
    prompts = []
    monkeypatch.setattr(conflicts, "complete", lambda system, messages, **k: prompts.append(messages[0]["content"]) or '{"conflicts": []}')
    with database.SessionLocal() as db:
        conflicts._run(db, {"doc_id": handbook["id"]})
        conflicts._run(db, {"doc_id": salary["id"]})
    general_prompt, restricted_prompt = prompts[-2], prompts[-1]
    assert "Salary bands" not in general_prompt  # General doc is not compared with HR-only text
    assert "notice period" in restricted_prompt  # an HR doc may be compared with General ones


# ---- Versions ----

def test_new_version_replaces_the_old_one_once_ready(app_client):
    owner = _signup(app_client)
    v1 = _upload(app_client, owner, "leave.txt", "Annual leave is 18 days.")
    resp = app_client.post(f"/documents/{v1['id']}/versions", headers=owner,
                           files={"file": ("leave.txt", io.BytesIO(b"Annual leave is 24 days."), "text/plain")})
    assert resp.status_code == 201
    v2 = resp.json()
    assert v2["version"] == 2 and v2["previous_version_id"] == v1["id"]

    listed = app_client.get("/documents", headers=owner).json()
    assert [d["id"] for d in listed] == [v2["id"]]
    assert app_client.get(f"/documents/{v1['id']}", headers=owner).json()["status"] == "superseded"
    answer = app_client.post("/chat/ask", headers=owner, json={"question": "How many days of annual leave?"}).json()
    assert {c.get("doc_id") for c in answer["citations"]} == {v2["id"]}

    detail = app_client.get(f"/documents/{v2['id']}/detail", headers=owner).json()
    assert [v["version"] for v in detail["versions"]] == [1, 2]
    assert app_client.post(f"/documents/{v1['id']}/versions", headers=owner,
                           files={"file": ("x.txt", io.BytesIO(b"x"), "text/plain")}).status_code == 409

    # Removing the new version brings the old one back.
    assert app_client.delete(f"/documents/{v2['id']}", headers=owner).status_code == 204
    assert app_client.get(f"/documents/{v1['id']}", headers=owner).json()["status"] == "ready"


def test_versions_stay_in_the_same_collection(app_client):
    owner, hr, staff, col, salary, _ = _setup_hr(app_client)
    v2 = app_client.post(f"/documents/{salary['id']}/versions", headers=owner,
                         files={"file": ("salaries.txt", io.BytesIO(b"Grade A earns 95000."), "text/plain")}).json()
    assert v2["collection_id"] == col["id"]
    assert app_client.get(f"/documents/{v2['id']}", headers=staff).status_code == 404


# ---- Verified answers ----

def test_verified_answer_is_reused_and_respects_access(app_client, monkeypatch):
    from app.services import generation

    owner = _signup(app_client)
    hr = _join(app_client, owner, "hr@acme.com", "MEMBER")
    staff = _join(app_client, owner, "staff@acme.com", "VIEWER")
    _upload(app_client, owner, "handbook.txt", "The notice period is 30 days for all staff.")
    first = app_client.post("/chat/ask", headers=owner, json={"question": "What is the notice period?"}).json()
    assert app_client.post(f"/chat/messages/{first['message_id']}/verify", headers=hr).status_code == 403
    assert app_client.post(f"/chat/messages/{first['message_id']}/verify", headers=owner).status_code == 201

    def boom(*a, **k):
        raise AssertionError("the model must not be called for a verified answer")

    monkeypatch.setattr(generation, "get_client", boom)
    again = app_client.post("/chat/ask", headers=staff, json={"question": "what is the NOTICE period"}).json()
    assert again["answer_kind"] == "verified" and again["answer"] == first["answer"]
    assert again["verified"]["by"] == "o@acme.com"

    insights = app_client.get("/insights", headers=owner).json()
    assert insights["verified_answers"][0]["question"] == "What is the notice period?"
    assert insights["verified_answers"][0]["current"] is True


def test_verified_answer_citing_a_restricted_document_is_not_shown_to_outsiders(app_client):
    owner, hr, staff, col, salary, handbook = _setup_hr(app_client)
    first = app_client.post("/chat/ask", headers=owner, json={"question": "salary bands for grade A"}).json()
    assert "salaries.txt" in {c["filename"] for c in first["citations"]}
    app_client.post(f"/chat/messages/{first['message_id']}/verify", headers=owner)
    assert app_client.post("/chat/ask", headers=hr, json={"question": "Salary bands for grade A?"}).json()["answer_kind"] == "verified"
    staff_answer = app_client.post("/chat/ask", headers=staff, json={"question": "Salary bands for grade A?"}).json()
    assert staff_answer["answer_kind"] != "verified"
    assert "salaries.txt" not in {c["filename"] for c in staff_answer["citations"]}


def test_verified_answer_stops_when_its_source_is_replaced(app_client):
    owner = _signup(app_client)
    v1 = _upload(app_client, owner, "leave.txt", "Annual leave is 18 days.")
    first = app_client.post("/chat/ask", headers=owner, json={"question": "How much annual leave?"}).json()
    app_client.post(f"/chat/messages/{first['message_id']}/verify", headers=owner)
    app_client.post(f"/documents/{v1['id']}/versions", headers=owner,
                    files={"file": ("leave.txt", io.BytesIO(b"Annual leave is 24 days."), "text/plain")})
    again = app_client.post("/chat/ask", headers=owner, json={"question": "How much annual leave?"}).json()
    assert again["answer_kind"] != "verified"
    current = app_client.get("/insights", headers=owner).json()["verified_answers"][0]["current"]
    assert current is False


def test_verified_answers_stream_too(app_client):
    owner = _signup(app_client)
    _upload(app_client, owner, "h.txt", "Notice is 30 days.")
    first = app_client.post("/chat/ask", headers=owner, json={"question": "notice?"}).json()
    app_client.post(f"/chat/messages/{first['message_id']}/verify", headers=owner)
    with app_client.stream("POST", "/chat/ask/stream", headers=owner, json={"question": "Notice?"}) as resp:
        body = b"".join(resp.iter_bytes())
    assert b'"answer_kind": "verified"' in body and b'"verified": {"by": "o@acme.com"' in body


# ---- Conflict inbox ----

def test_reviewing_conflicts_clears_the_alert(app_client):
    import app.core.database as database
    from app.models.models import Document

    owner = _signup(app_client)
    member = _join(app_client, owner, "m@acme.com")
    doc = _upload(app_client, owner, "a.txt", "Notice is 45 days.")
    with database.SessionLocal() as db:
        row = db.get(Document, doc["id"])
        row.conflicts = json.dumps([{"topic": "Notice", "this_says": "45", "other_file": "b.txt", "other_says": "30"}])
        db.commit()
    assert app_client.get("/home", headers=owner).json()["alerts"]["conflicts"] == ["a.txt"]
    assert len(app_client.get("/insights", headers=owner).json()["open_conflicts"]) == 1
    assert app_client.post(f"/documents/{doc['id']}/conflicts", headers=member, json={"state": "resolved"}).status_code == 403
    assert app_client.post(f"/documents/{doc['id']}/conflicts", headers=owner, json={"state": "resolved"}).json()["conflicts_state"] == "resolved"
    assert app_client.get("/home", headers=owner).json()["alerts"]["conflicts"] == []
    assert app_client.get("/insights", headers=owner).json()["open_conflicts"] == []


def test_document_detail_shows_history_and_uploader(app_client):
    owner = _signup(app_client)
    doc = _upload(app_client, owner, "a.txt", "Notice is 45 days.")
    detail = app_client.get(f"/documents/{doc['id']}/detail", headers=owner).json()
    assert detail["uploaded_by_email"] == "o@acme.com" and detail["can_manage"] is True
    assert [e["to_status"] for e in detail["events"]][-1] == "ready"
