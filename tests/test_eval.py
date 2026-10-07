"""Sprint 3: routing, target-document resolution, follow-ups, and the scored
demo-company eval (pipeline check with a deterministic word-hashing embedder)."""
import hashlib

import numpy as np
import pytest


class WordHashEmbedder:
    """Bag-of-words vectors: deterministic, offline, and good enough to check
    that the right document reaches the top. Real-model numbers come from
    `python -m eval.run_eval`."""

    STOP = {"the", "a", "an", "is", "of", "to", "do", "i", "my", "we", "what", "how", "can", "for", "in", "on",
            "and", "are", "be", "get", "per", "much", "many", "much"}

    def embed(self, texts):
        for text in texts:
            vector = np.zeros(384, dtype=np.float32)
            for word in text.lower().replace(",", " ").replace(".", " ").replace("?", " ").split():
                if word not in self.STOP:
                    vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % 384] += 1
            yield vector / (np.linalg.norm(vector) or 1)


@pytest.fixture()
def demo(app_client, monkeypatch):
    import app.core.database as database
    from app.services import rag
    from eval.harness import seed_demo_org

    monkeypatch.setattr(rag, "get_embedder", lambda: WordHashEmbedder())
    db = database.SessionLocal()
    org_id, user_id = seed_demo_org(db)
    yield db, org_id
    db.close()


# ---- The scored eval ----

def test_demo_company_eval_meets_the_bar(demo):
    from eval.harness import run

    db, org_id = demo
    result = run(db, org_id, k=6)
    print("\n" + result.table())
    assert result.retrieval_hits / result.retrieval_total >= 0.9, result.table()
    assert result.routing_correct == result.routing_total, result.table()


def test_all_demo_documents_ingest(demo):
    from sqlalchemy import select
    from app.models.models import Document

    db, org_id = demo
    statuses = {d.filename: d.status for d in db.scalars(select(Document).where(Document.org_id == org_id))}
    assert len(statuses) == 5 and set(statuses.values()) == {"ready"}


# ---- Routing ----

@pytest.mark.parametrize("question", [
    "review and rate my resume out of 10",
    "Summarise the travel policy",
    "give me the key points of the benefits guide",
    "compare the two contracts",
    "explain the indexed document",
    "hi, explain me the indexed document like, what it the data here now?",
    "what is this document about?",
    "can you give feedback on my cover letter",
])
def test_document_tasks_are_detected(question):
    from app.services.answer_plan import is_document_task
    assert is_document_task(question)


@pytest.mark.parametrize("question", [
    "What is the notice period?",
    "How many days of annual leave do I get?",
    "Who approves international travel?",
    "Is MFA mandatory for email?",
])
def test_plain_questions_are_not_document_tasks(question):
    from app.services.answer_plan import is_document_task
    assert not is_document_task(question)


def test_file_named_in_question_wins(demo):
    from app.services.answer_plan import plan_answer

    db, org_id = demo
    plan = plan_answer(db, org_id, "Review the IT security policy and rate it")
    assert plan.mode == "document" and plan.target_docs == ["it_security_policy.txt"]
    assert {c["filename"] for c in plan.chunks} == {"it_security_policy.txt"}
    assert "complete" in plan.note


def test_numbers_in_file_names_resolve_the_document(app_client, monkeypatch):
    """The live failure: 'here is the same resume 127162001, review and rate it'."""
    import app.core.database as database
    from app.models.models import Document, Org, User
    from app.services import ingestion, jobs, lifecycle, rag
    from app.services.answer_plan import plan_answer

    monkeypatch.setattr(rag, "get_embedder", lambda: WordHashEmbedder())
    with database.SessionLocal() as db:
        org = Org(name="Atribs")
        db.add(org)
        db.flush()
        user = User(email="o@a.com", hashed_password="x", org_id=org.id, role="OWNER")
        db.add(user)
        db.flush()
        for name, text in [
            ("127162001_Anirudh_K_ Resume.pdf", "Anirudh K. MTech AI. Projects: DocuMind RAG assistant. Skills: Python."),
            ("127162013_Mallibhat Vitesh Bharadwaj.pdf", "Vitesh. BTech. Projects: robotics. Skills: C++."),
        ]:
            doc = Document(org_id=org.id, uploaded_by=user.id, filename=name, status="queued")
            db.add(doc)
            db.flush()
            lifecycle.record_created(db, doc)
            jobs.enqueue(db, ingestion.KIND, {"doc_id": doc.id, "org_id": org.id, "text": text})
        db.commit()
        jobs.drain()

        plan = plan_answer(db, org.id, "here is the same resume 127162001, review and rate it to me?")
        assert plan.target_docs == ["127162001_Anirudh_K_ Resume.pdf"]
        plan = plan_answer(db, org.id, "i have uploaded a new document. based on that please review and rate it")
        assert plan.mode == "document" and len(plan.target_docs) == 1  # latest upload


def test_long_documents_send_selected_passages_and_say_so(demo, monkeypatch):
    from app.core.config import get_settings
    from app.services.answer_plan import plan_answer

    db, org_id = demo
    monkeypatch.setattr(get_settings(), "whole_doc_chars", 700)
    plan = plan_answer(db, org_id, "summarise the employee handbook")
    assert "selected passages" in plan.note
    indexes = [c["chunk_index"] for c in plan.chunks]
    assert indexes == sorted(indexes) and sum(len(c["text"]) for c in plan.chunks) <= 700


def test_questions_naming_a_file_search_only_that_file(demo):
    from app.services.answer_plan import plan_answer

    db, org_id = demo
    plan = plan_answer(db, org_id, "In the travel expense policy, what is the limit?")
    assert plan.mode == "question" and {c["filename"] for c in plan.chunks} == {"travel_expense_policy.txt"}


def test_short_follow_ups_borrow_the_previous_question():
    from app.services.answer_plan import retrieval_query

    history = [{"role": "user", "content": "What is the hotel limit in Mumbai?"},
               {"role": "assistant", "content": "Rs 6,000 per night [1]."}]
    assert retrieval_query("and in Pune?", history) == "What is the hotel limit in Mumbai? and in Pune?"
    assert retrieval_query("How many sick leave days do employees get each year?", history) == (
        "How many sick leave days do employees get each year?")


# ---- Citation marker variants ----

@pytest.mark.parametrize("raw,expected", [
    ("matching 【1】.", "matching [1]."),
    ("a 【2†L3-L9】 b", "a [2] b"),
    ("x ［3］", "x [3]"),
    ("y [^1]", "y [1]"),
    ("z [Source 2]", "z [2]"),
    ("w [1，2]", "w [1, 2]"),
    ("keep [link](http://a), [abc] and [2026]", "keep [link](http://a), [abc] and [2026]"),
])
def test_citation_variants_are_normalised(raw, expected):
    from app.services.citations import normalize_markers
    assert normalize_markers(raw) == expected


def test_fullwidth_marker_selects_only_that_source():
    """The live bug: 【1】 was missed, so all three sources were shown."""
    from app.services.citations import select_citations

    chunks = [{"filename": "r.pdf", "chunk_index": i} for i in (4, 3, 1)]
    assert select_citations("automated candidate matching 【1】", chunks) == [
        {"filename": "r.pdf", "chunk_index": 4, "n": 1}]
