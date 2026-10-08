"""Sprint 5: heading-aware chunks, hybrid search, citation runs, research agent, conflict checker."""
import io
import json

import pytest
from sqlalchemy import select

from tests.test_eval import WordHashEmbedder

PASSWORD = "password123"


def signup(client, email="a@acme.com", org_name="Acme"):
    resp = client.post("/auth/signup", json={"email": email, "password": PASSWORD, "org_name": org_name})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def upload(client, headers, name, body):
    return client.post("/documents", headers=headers, files={"file": (name, io.BytesIO(body), "text/plain")}).json()


# ---- Chunking ----

def test_chunks_carry_their_heading():
    from app.services.rag import chunk_document

    text = ("Leave Policy\n\n1. Annual leave\nEmployees get 24 days of paid leave each year. " + "x " * 150
            + "\n\n2. Sick leave\nSick leave is 12 days a year and needs a certificate after 2 days. " + "y " * 150)
    chunks = chunk_document(text)
    assert any("1. Annual leave\nEmployees get 24 days" in c for c in chunks)
    assert any(c.startswith("2. Sick leave\nSick leave is 12 days") for c in chunks)


def test_tiny_sections_are_merged_and_lists_are_not_headings():
    from app.services.rag import chunk_document, _looks_like_heading

    assert _looks_like_heading("Technical Skills") and _looks_like_heading("4. Notice period")
    assert not _looks_like_heading("Python, Java, C++, Flask, React")
    assert not _looks_like_heading("M.Tech AI & DS, SASTRA, CGPA 7.7")
    chunks = chunk_document("Education\nM.Tech, 2026\n\nSkills\nPython, SQL\n\nProjects\nDocuMind, Vigil")
    assert len(chunks) == 1 and "Education" in chunks[0] and "Projects" in chunks[0]


def test_text_without_headings_uses_plain_chunking():
    from app.services.rag import chunk_document, chunk_text

    text = "This is a plain paragraph. It has no headings at all. " * 30
    assert chunk_document(text) == chunk_text(text)


# ---- Hybrid search ----

def test_keyword_search_finds_exact_identifiers_embeddings_miss(app_client, monkeypatch):
    """With an embedding that can't tell the documents apart at all, the exact
    code still reaches the top results through keyword search."""
    import numpy as np
    import app.core.database as database
    from app.services import rag

    class Blurry:  # every text gets the same vector: vector search alone is a coin toss
        def embed(self, texts):
            for _ in texts:
                yield np.ones(384, dtype=np.float32) / np.sqrt(384)

    monkeypatch.setattr(rag, "get_embedder", lambda: Blurry())
    headers = signup(app_client)
    for i in range(5):
        upload(app_client, headers, f"policy_{i}.txt", f"Policy HR-{100 + i} covers topic number {i}.".encode())
    with database.SessionLocal() as db:
        org_id = db.scalar(select(__import__("app.models.models", fromlist=["Org"]).Org.id))
        assert "policy_3.txt" in [h["filename"] for h in rag.retrieve_chunks(
            org_id, "What does HR-103 cover?", top_k=2, db=db)]
        vector_only = [h["filename"] for h in rag.retrieve_chunks(
            org_id, "What does HR-103 cover?", top_k=2, db=db, hybrid=False)]
        assert "policy_3.txt" not in vector_only


def test_hybrid_beats_or_matches_vector_only_on_the_demo_eval(app_client, monkeypatch):
    import app.core.database as database
    from app.services import rag
    from eval.harness import run, seed_demo_org

    monkeypatch.setattr(rag, "get_embedder", lambda: WordHashEmbedder())
    with database.SessionLocal() as db:
        org_id, _ = seed_demo_org(db)
        hybrid = run(db, org_id, hybrid=True)
        vector = run(db, org_id, hybrid=False)
    assert hybrid.retrieval_hits >= vector.retrieval_hits
    assert hybrid.retrieval_hits == hybrid.retrieval_total, hybrid.table()


def test_keyword_terms_fold_plurals_and_drop_stopwords():
    from app.services.rag import keyword_terms
    assert keyword_terms("What are the passwords policies?") == ["password", "policy"]


# ---- Citation runs ----

@pytest.mark.parametrize("raw,expected", [
    ("domains[3][3]", "domains[3]"),
    ("A[1][2][3].", "A[1, 2, 3]."),
    ("x [3], [4] y", "x [3, 4] y"),
    ("【1】【1】", "[1]"),
    ("see [1](http://x) [2]", "see [1](http://x) [2]"),
])
def test_adjacent_markers_are_merged(raw, expected):
    from app.services.citations import normalize_markers
    assert normalize_markers(raw) == expected


# ---- Research agent ----

class ScriptedLLM:
    """Replays planner replies in order and records what it was shown."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def __call__(self, system, messages, max_tokens=600):
        self.seen.append(messages[-1]["content"])
        return self.replies.pop(0) if self.replies else '{"action": "finish"}'


@pytest.fixture()
def demo(app_client, monkeypatch):
    import app.core.database as database
    from app.services import rag
    from eval.harness import seed_demo_org

    monkeypatch.setattr(rag, "get_embedder", lambda: WordHashEmbedder())
    db = database.SessionLocal()
    org_id, _ = seed_demo_org(db)
    yield db, org_id
    db.close()


def test_agent_runs_searches_and_collects_evidence(demo, monkeypatch):
    from app.services import research_agent

    db, org_id = demo
    llm = ScriptedLLM([
        '{"thought": "travel side", "action": "search", "query": "expense claim deadline", "filename": "travel_expense_policy.txt"}',
        'Sure! {"thought": "handbook side", "action": "read", "filename": "employee_handbook.txt"}',
        '{"thought": "enough", "action": "finish"}',
    ])
    monkeypatch.setattr(research_agent, "complete", llm)
    steps, result = research_agent.collect(
        research_agent.run_research(db, org_id, "Do the travel and handbook rules conflict on deadlines?"))

    assert [s["action"] for s in steps] == ["search", "read", "finish"]
    assert steps[0]["files"] == ["travel_expense_policy.txt"]
    assert {c["filename"] for c in result.chunks} == {"travel_expense_policy.txt", "employee_handbook.txt"}
    assert result.stopped == "finished"
    assert "employee_handbook.txt" in llm.seen[0]  # the planner saw the document list
    assert "<source" in llm.seen[1]  # observations are wrapped as data


def test_agent_respects_the_step_limit(demo, monkeypatch):
    from app.services import research_agent

    db, org_id = demo
    loop = '{"action": "search", "query": "leave"}'
    monkeypatch.setattr(research_agent, "complete", ScriptedLLM([loop] * 20))
    steps, result = research_agent.collect(research_agent.run_research(db, org_id, "conflicts across all policies"))
    assert len(steps) == research_agent.MAX_STEPS and result.stopped == "step_limit"


def test_agent_falls_back_to_normal_search_when_the_llm_fails(demo, monkeypatch):
    from app.services import research_agent
    from app.services.generation import LLMUnavailable

    def broken(*a, **k):
        raise LLMUnavailable("down")

    db, org_id = demo
    monkeypatch.setattr(research_agent, "complete", broken)
    steps, result = research_agent.collect(research_agent.run_research(db, org_id, "hotel limit in Mumbai"))
    assert steps == [] and result.stopped == "llm_unavailable" and result.chunks  # never answers from nothing


def test_agent_stops_on_unusable_output_and_ignores_unknown_files(demo, monkeypatch):
    from app.services import research_agent

    db, org_id = demo
    monkeypatch.setattr(research_agent, "complete", ScriptedLLM([
        '{"action": "read", "filename": "secret_other_org.pdf"}', "I think the answer is 42.",
    ]))
    steps, result = research_agent.collect(research_agent.run_research(db, org_id, "conflicts across all policies"))
    assert steps[0]["found"] == 0 and result.stopped == "bad_output"


def test_research_routing():
    from app.services.research_agent import is_research_question
    assert is_research_question("Do the travel and expense policies conflict anywhere?")
    assert is_research_question("Which policies mention approvals across all documents?")
    assert not is_research_question("What is the hotel limit in Mumbai?")


def test_stream_shows_research_steps_and_saves_the_trace(app_client, monkeypatch):
    from app.services import rag, research_agent

    monkeypatch.setattr(rag, "get_embedder", lambda: WordHashEmbedder())
    monkeypatch.setattr(research_agent, "complete", ScriptedLLM([
        '{"thought": "look", "action": "search", "query": "notice period"}', '{"action": "finish"}',
    ]))
    headers = signup(app_client)
    upload(app_client, headers, "handbook.txt", b"Notice period is 30 days after probation.")
    with app_client.stream("POST", "/chat/ask/stream", headers=headers,
                           json={"question": "notice period", "mode": "research"}) as r:
        events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: {")]
    assert [e["step"]["action"] for e in events if "step" in e] == ["search", "finish"]
    assert any("text" in e for e in events)

    convo = app_client.get("/chat/conversations", headers=headers).json()[0]
    detail = app_client.get(f"/chat/conversations/{convo['id']}", headers=headers).json()
    assert detail["messages"][1]["research_steps"][0]["query"] == "notice period"


def test_fast_mode_never_uses_the_agent(app_client, monkeypatch):
    from app.services import research_agent

    def boom(*a, **k):
        raise AssertionError("agent should not run")

    monkeypatch.setattr(research_agent, "complete", boom)
    headers = signup(app_client)
    upload(app_client, headers, "a.txt", b"Policies may conflict.")
    resp = app_client.post("/chat/ask", headers=headers,
                           json={"question": "do the policies conflict across all documents?", "mode": "fast"})
    assert resp.status_code == 200 and resp.json()["research_steps"] is None


# ---- Conflict checker ----

def test_parse_conflicts_drops_unknown_files_and_bad_items():
    from app.services.conflicts import parse_conflicts

    reply = json.dumps({"conflicts": [
        {"topic": "Notice", "this_says": "45 days", "other_file": "handbook.txt", "other_says": "30 days"},
        {"topic": "x", "this_says": "y", "other_file": "made_up.txt", "other_says": "z"},
        "garbage",
    ]})
    assert parse_conflicts(reply, {"handbook.txt"}) == [
        {"topic": "Notice", "this_says": "45 days", "other_file": "handbook.txt", "other_says": "30 days"}]
    with pytest.raises(ValueError):
        parse_conflicts("no json here", {"handbook.txt"})


def test_new_upload_is_checked_against_existing_documents(app_client, monkeypatch):
    from app.services import conflicts, rag, summaries

    monkeypatch.setattr(rag, "get_embedder", lambda: WordHashEmbedder())
    monkeypatch.setattr(summaries, "generate_answer", lambda *a, **k: json.dumps(
        {"summary": "A policy.", "questions": ["What is the notice period?"]}))
    seen = {}

    def fake_complete(system, messages, max_tokens=600):
        seen["prompt"] = messages[0]["content"]
        return json.dumps({"conflicts": [{"topic": "Notice period", "this_says": "45 days' notice",
                                          "other_file": "handbook.txt", "other_says": "30 days' notice"}]})

    monkeypatch.setattr(conflicts, "complete", fake_complete)
    headers = signup(app_client)
    first = upload(app_client, headers, "handbook.txt", b"Notice period: employees give 30 days notice.")
    assert app_client.get(f"/documents/{first['id']}", headers=headers).json()["conflicts"] == []

    second = upload(app_client, headers, "new_policy.txt", b"Notice period: employees give 45 days notice.")
    doc = app_client.get(f"/documents/{second['id']}", headers=headers).json()
    assert doc["conflicts"][0]["other_file"] == "handbook.txt"
    assert "NEW document: new_policy.txt" in seen["prompt"] and "30 days" in seen["prompt"]
