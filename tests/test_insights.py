"""Sprint 4a: auto summaries + suggested questions, answer kinds, feedback, insights."""
import io
import json

import pytest
from sqlalchemy import select

PASSWORD = "password123"


def signup(client, email, org_name="Acme"):
    resp = client.post("/auth/signup", json={"email": email, "password": PASSWORD, "org_name": org_name})
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def join(client, admin, email, role):
    token = client.post("/org/invites", headers=admin, json={"email": email, "role": role}).json()["token"]
    resp = client.post("/auth/accept-invite", json={"token": token, "password": PASSWORD})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def upload(client, headers, name="handbook.txt", body=b"Notice period is 30 days. Probation is 6 months."):
    return client.post("/documents", headers=headers, files={"file": (name, io.BytesIO(body), "text/plain")})


SUMMARY_JSON = json.dumps({
    "summary": "The employee handbook covers notice periods [1] and probation.",
    "questions": ["What is the notice period?", "How long is probation?", "Who approves leave? [2]"],
})


@pytest.fixture()
def fake_summariser(monkeypatch):
    from app.services import summaries
    monkeypatch.setattr(summaries, "generate_answer", lambda *a, **k: f"Here you go:\n```json\n{SUMMARY_JSON}\n```")


# ---- Summaries + suggestions ----

def test_ready_documents_get_a_summary_and_starter_questions(app_client, fake_summariser):
    headers = signup(app_client, "a@acme.com")
    doc = upload(app_client, headers).json()
    final = app_client.get(f"/documents/{doc['id']}", headers=headers).json()
    assert final["summary"] == "The employee handbook covers notice periods and probation."
    assert final["suggested_questions"] == ["What is the notice period?", "How long is probation?",
                                            "Who approves leave?"]
    suggestions = app_client.get("/documents/suggestions", headers=headers).json()
    assert [s["question"] for s in suggestions][:2] == ["What is the notice period?", "How long is probation?"]
    assert all(s["filename"] == "handbook.txt" for s in suggestions)


def test_suggestions_are_org_scoped(app_client, fake_summariser):
    a = signup(app_client, "a@a.com", "OrgA")
    b = signup(app_client, "b@b.com", "OrgB")
    upload(app_client, a)
    assert app_client.get("/documents/suggestions", headers=b).json() == []


def test_a_fallback_reply_is_never_saved_as_a_summary(app_client, monkeypatch):
    import app.core.database as database
    from app.models.models import Job
    from app.services import summaries
    from app.services.generation import FALLBACK_PREFIX

    monkeypatch.setattr(summaries, "generate_answer", lambda *a, **k: f"{FALLBACK_PREFIX} closest passage...")
    headers = signup(app_client, "a@acme.com")
    doc = upload(app_client, headers).json()
    assert app_client.get(f"/documents/{doc['id']}", headers=headers).json()["summary"] is None
    with database.SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.kind == "summarize_document"))
        assert job.status == "queued" and "fallback" in job.last_error  # will retry later


def test_no_summary_job_without_an_llm_key(app_client, monkeypatch):
    import app.core.database as database
    from app.models.models import Job
    from app.services import generation

    monkeypatch.setattr(generation.settings, "anthropic_api_key", None)
    headers = signup(app_client, "a@acme.com")
    upload(app_client, headers)
    with database.SessionLocal() as db:
        assert db.scalar(select(Job).where(Job.kind == "summarize_document")) is None


@pytest.mark.parametrize("reply", ["not json at all", '{"summary": "", "questions": []}'])
def test_unusable_summaries_are_rejected(reply):
    from app.services.summaries import parse_summary
    with pytest.raises(ValueError):
        parse_summary(reply)


# ---- Answer kinds + feedback ----

def _ask(client, headers, question):
    return client.post("/chat/ask", headers=headers, json={"question": question}).json()


def test_answer_kinds_are_recorded(app_client, monkeypatch):
    from app.routes import chat

    headers = signup(app_client, "a@acme.com")
    assert _ask(app_client, headers, "anything?")["answer_kind"] == "no_sources"
    upload(app_client, headers)
    monkeypatch.setattr(chat, "generate_answer", lambda *a, **k: "Notice is 30 days [1].")
    assert _ask(app_client, headers, "notice period?")["answer_kind"] == "answered"
    monkeypatch.setattr(chat, "generate_answer", lambda *a, **k: "Your documents don't mention a dress code.")
    assert _ask(app_client, headers, "dress code?")["answer_kind"] == "abstained"


def test_streamed_answers_return_an_id_that_can_be_rated(app_client):
    headers = signup(app_client, "a@acme.com")
    upload(app_client, headers)
    with app_client.stream("POST", "/chat/ask/stream", headers=headers, json={"question": "notice"}) as r:
        events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: {")]
    final = next(e for e in events if "message_id" in e)
    assert final["answer_kind"] == "answered"
    resp = app_client.post(f"/chat/messages/{final['message_id']}/feedback", headers=headers, json={"value": 1})
    assert resp.json() == {"feedback": 1}


def test_feedback_only_on_your_own_assistant_messages(app_client):
    owner = signup(app_client, "a@acme.com")
    member = join(app_client, owner, "m@acme.com", "MEMBER")
    upload(app_client, owner)
    answer = _ask(app_client, owner, "notice")
    path = f"/chat/messages/{answer['message_id']}/feedback"
    assert app_client.post(path, headers=member, json={"value": -1}).status_code == 404
    assert app_client.post(path, headers=owner, json={"value": 2}).status_code == 422
    assert app_client.post(path, headers=owner, json={"value": -1}).json() == {"feedback": -1}
    assert app_client.post(path, headers=owner, json={"value": 0}).json() == {"feedback": None}

    convo = app_client.get("/chat/conversations", headers=owner).json()[0]
    user_msg = app_client.get(f"/chat/conversations/{convo['id']}", headers=owner).json()["messages"][0]
    assert app_client.post(f"/chat/messages/{user_msg['id']}/feedback", headers=owner,
                           json={"value": 1}).status_code == 404


# ---- Insights ----

def test_insights_show_gaps_top_questions_and_unhelpful_answers(app_client, monkeypatch):
    from app.routes import chat

    owner = signup(app_client, "a@acme.com")
    upload(app_client, owner)
    monkeypatch.setattr(chat, "generate_answer", lambda *a, **k: "Notice is 30 days [1].")
    first = _ask(app_client, owner, "What is the notice period?")
    _ask(app_client, owner, "what is the notice period")
    monkeypatch.setattr(chat, "generate_answer", lambda *a, **k: "Your documents don't cover the dress code.")
    _ask(app_client, owner, "Is there a dress code?")
    app_client.post(f"/chat/messages/{first['message_id']}/feedback", headers=owner, json={"value": -1})

    data = app_client.get("/insights", headers=owner).json()
    assert data["totals"]["questions"] == 3
    assert data["totals"]["answered"] == 2 and data["totals"]["not_in_documents"] == 1
    assert data["totals"]["not_helpful"] == 1
    assert data["top_questions"][0] == {"question": "What is the notice period?", "count": 2}
    assert [g["question"] for g in data["knowledge_gaps"]] == ["Is there a dress code?"]
    assert data["top_documents"] == [{"filename": "handbook.txt", "answers": 2}]
    assert data["unhelpful_answers"][0]["question"] == "What is the notice period?"
    assert "email" not in json.dumps(data["unhelpful_answers"])  # no asker identity


def test_insights_are_admin_only_and_org_scoped(app_client):
    owner = signup(app_client, "a@acme.com")
    member = join(app_client, owner, "m@acme.com", "MEMBER")
    other = signup(app_client, "b@b.com", "OrgB")
    _ask(app_client, other, "a question from another org")
    assert app_client.get("/insights", headers=member).status_code == 403
    assert app_client.get("/insights", headers=owner).json()["totals"]["questions"] == 0
