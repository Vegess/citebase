"""Sprint 2: vectors in the DB, document lifecycle, job queue, per-org quota, metrics."""
import io
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

PASSWORD = "password123"


def signup(client, email, org_name="Acme"):
    resp = client.post("/auth/signup", json={"email": email, "password": PASSWORD, "org_name": org_name})
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def upload(client, headers, name="handbook.txt", body=b"Notice period is 30 days. Probation is 7 days."):
    return client.post("/documents", headers=headers, files={"file": (name, io.BytesIO(body), "text/plain")})


def settings():
    from app.core.config import get_settings
    return get_settings()


# ---- Lifecycle ----

def test_upload_walks_the_lifecycle_and_records_history(app_client):
    headers = signup(app_client, "a@acme.com")
    doc = upload(app_client, headers).json()
    events = app_client.get(f"/documents/{doc['id']}/events", headers=headers).json()
    assert [(e["from_status"], e["to_status"]) for e in events] == [
        (None, "queued"), ("queued", "chunking"), ("chunking", "embedding"), ("embedding", "ready"),
    ]
    final = app_client.get(f"/documents/{doc['id']}", headers=headers).json()
    assert final["status"] == "ready" and final["num_chunks"] >= 1 and final["truncated"] is False


def test_illegal_transitions_are_refused(app_client):
    import app.core.database as database
    from app.services import lifecycle

    headers = signup(app_client, "a@acme.com")
    doc = upload(app_client, headers).json()
    with database.SessionLocal() as db:
        with pytest.raises(lifecycle.InvalidTransition):
            lifecycle.transition(db, doc["id"], lifecycle.EMBEDDING)  # ready -> embedding is not a legal move


def test_other_orgs_cannot_read_document_history(app_client):
    owner = signup(app_client, "a@a.com", "OrgA")
    other = signup(app_client, "b@b.com", "OrgB")
    doc = upload(app_client, owner).json()
    assert app_client.get(f"/documents/{doc['id']}/events", headers=other).status_code == 404


# ---- Upload validation ----

def test_empty_and_imageonly_files_are_rejected_up_front(app_client):
    from pypdf import PdfWriter

    headers = signup(app_client, "a@acme.com")
    assert upload(app_client, headers, "blank.txt", b"   \n\n ").status_code == 422

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    resp = app_client.post("/documents", headers=headers,
                           files={"file": ("scan.pdf", buffer.getvalue(), "application/pdf")})
    assert resp.status_code == 422
    assert "Scanned PDFs" in resp.json()["detail"]


def test_long_documents_are_flagged_truncated(app_client, monkeypatch):
    monkeypatch.setattr(settings(), "max_document_chars", 40)
    headers = signup(app_client, "a@acme.com")
    doc = upload(app_client, headers, body=b"A sentence that is long. " * 10).json()
    assert doc["truncated"] is True and doc["char_count"] == 40


# ---- Vectors ----

def test_retrieval_only_returns_ready_documents_of_the_callers_org(app_client):
    import app.core.database as database
    from app.models.models import Document
    from app.services import rag

    a = signup(app_client, "a@a.com", "OrgA")
    b = signup(app_client, "b@b.com", "OrgB")
    doc_a = upload(app_client, a, "a.txt", b"Leave policy: 24 days of annual leave.").json()
    upload(app_client, b, "b.txt", b"Leave policy: 12 days of annual leave.")

    with database.SessionLocal() as db:
        org_a = db.get(Document, doc_a["id"]).org_id
        assert [h["filename"] for h in rag.retrieve_chunks(org_a, "annual leave", top_k=10, db=db)] == ["a.txt"]
        db.get(Document, doc_a["id"]).status = "failed"
        db.commit()
        assert rag.retrieve_chunks(org_a, "annual leave", top_k=10, db=db) == []


# ---- Jobs ----

def _jobs():
    import app.core.database as database
    from app.models.models import Job
    with database.SessionLocal() as db:
        # Ingest jobs only: with an LLM key configured, a ready document also
        # queues a summarize_document job (Sprint 4a), covered in test_insights.py.
        return [(j.status, j.attempts, json.loads(j.payload), j.last_error)
                for j in db.scalars(select(Job).where(Job.kind == "ingest_document"))]


def test_finished_jobs_drop_the_document_text(app_client):
    headers = signup(app_client, "a@acme.com")
    upload(app_client, headers)
    [(status, attempts, payload, _)] = _jobs()
    assert status == "done" and attempts == 1
    assert "text" not in payload and "doc_id" in payload


def test_transient_failure_is_retried_then_succeeds(app_client, monkeypatch):
    import app.core.database as database
    from app.models.models import Job
    from app.services import jobs, rag

    real = rag.get_embedder()
    calls = {"n": 0}

    class Flaky:
        def embed(self, texts):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("model download hiccup")
            return real.embed(texts)

    monkeypatch.setattr(rag, "get_embedder", lambda: Flaky())
    headers = signup(app_client, "a@acme.com")
    doc = upload(app_client, headers).json()

    after_first = app_client.get(f"/documents/{doc['id']}", headers=headers).json()
    assert after_first["status"] == "queued"
    assert "retrying" in after_first["error"]
    [(status, attempts, _, last_error)] = _jobs()
    assert (status, attempts) == ("queued", 1) and "ConnectionError" in last_error

    with database.SessionLocal() as db:  # skip the backoff wait
        for job in db.scalars(select(Job)):
            job.run_after = job.created_at
        db.commit()
    jobs.drain()

    final = app_client.get(f"/documents/{doc['id']}", headers=headers).json()
    assert final["status"] == "ready" and final["error"] is None


def test_permanent_failure_marks_document_failed_after_max_attempts(app_client, monkeypatch):
    import app.core.database as database
    from app.models.models import Job
    from app.services import jobs, rag

    class Broken:
        def embed(self, texts):
            raise RuntimeError("embedding model unavailable")

    monkeypatch.setattr(rag, "get_embedder", lambda: Broken())
    headers = signup(app_client, "a@acme.com")
    doc = upload(app_client, headers).json()
    for _ in range(3):
        with database.SessionLocal() as db:
            for job in db.scalars(select(Job)):
                job.run_after = job.created_at
            db.commit()
        jobs.drain()

    final = app_client.get(f"/documents/{doc['id']}", headers=headers).json()
    assert final["status"] == "failed" and "file again" in final["error"]
    [(status, attempts, payload, _)] = _jobs()
    assert (status, attempts) == ("failed", 3) and "text" not in payload


def test_deleting_a_queued_document_cancels_its_job_cleanly(app_client, monkeypatch):
    from app.models.models import DocumentChunk
    import app.core.database as database
    from app.services import jobs

    monkeypatch.setattr(settings(), "worker_mode", "off")  # keep the job queued
    headers = signup(app_client, "a@acme.com")
    doc = upload(app_client, headers).json()
    assert app_client.delete(f"/documents/{doc['id']}", headers=headers).status_code == 204

    jobs.drain()
    [(status, _, _, _)] = _jobs()
    assert status == "done"
    with database.SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(DocumentChunk)) == 0


def test_stale_running_jobs_are_requeued(app_client):
    from datetime import datetime, timedelta, timezone
    import app.core.database as database
    from app.models.models import Job
    from app.services import jobs

    with database.SessionLocal() as db:
        db.add(Job(kind="ingest_document", payload="{}", status="running",
                   locked_at=datetime.now(timezone.utc) - timedelta(hours=1)))
        db.commit()
        assert jobs.requeue_stale(db) == 1


# ---- Quota ----

def test_per_org_cap_blocks_the_whole_workspace(app_client, monkeypatch):
    import app.core.database as database
    from app.services import quota

    monkeypatch.setattr(settings(), "daily_question_cap", 100)
    monkeypatch.setattr(settings(), "per_org_daily_cap", 3)
    monkeypatch.setattr(settings(), "per_user_daily_cap", 100)
    with database.SessionLocal() as db:
        for user in ("u1", "u2", "u3"):
            quota.reserve_question(db, user, org_id="org-1")
        db.commit()
        with pytest.raises(HTTPException) as blocked:
            quota.reserve_question(db, "u4", org_id="org-1")
        assert "workspace" in blocked.value.detail
        quota.reserve_question(db, "u5", org_id="org-2")  # other orgs unaffected
        db.commit()


def test_a_blocked_reservation_changes_no_counter(app_client, monkeypatch):
    import app.core.database as database
    from app.models.models import QuestionUsage
    from app.services import quota

    monkeypatch.setattr(settings(), "daily_question_cap", 100)
    monkeypatch.setattr(settings(), "per_org_daily_cap", 100)
    monkeypatch.setattr(settings(), "per_user_daily_cap", 1)
    with database.SessionLocal() as db:
        quota.reserve_question(db, "u1", org_id="org-1")
        db.commit()
        with pytest.raises(HTTPException):
            quota.reserve_question(db, "u1", org_id="org-1")
        db.commit()
        counts = {r.scope: r.question_count for r in db.scalars(select(QuestionUsage))}
        assert counts == {"global": 1, "org:org-1": 1, "u1": 1}


# ---- Metrics (Vigil Phase 0) ----

def test_metrics_endpoint_is_hidden_without_a_token(app_client):
    assert app_client.get("/metrics").status_code == 404


def test_metrics_require_the_right_token_and_count_fallbacks(app_client, monkeypatch):
    from app.services import generation

    monkeypatch.setattr(settings(), "metrics_token", "s3cret")
    assert app_client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401

    headers = signup(app_client, "a@acme.com")
    upload(app_client, headers)
    monkeypatch.setattr(generation.settings, "anthropic_api_key", None)  # simulate a lost key
    app_client.post("/chat/ask", headers=headers, json={"question": "notice period"})

    m = app_client.get("/metrics", headers={"Authorization": "Bearer s3cret"}).json()
    assert m["fallback_total"] == 1 and m["fallback_reasons"] == {"missing_api_key": 1}
    assert m["fallback_rate_5m"] == 1.0
    assert m["documents_by_status"] == {"ready": 1} and m["chunks_total"] >= 1
    assert m["jobs_by_status"].get("done", 0) >= 1

    logs = app_client.get("/metrics/logs?contains=fallback", headers={"Authorization": "Bearer s3cret"}).json()
    assert logs and logs[-1]["fallback"] is True and logs[-1]["fallback_reason"] == "missing_api_key"


def test_json_log_formatter_never_crashes_on_missing_fields():
    import logging
    from app.core.logging_setup import JsonFormatter

    record = logging.LogRecord("x", logging.WARNING, __file__, 1, "hello %s", ("world",), None)
    line = json.loads(JsonFormatter().format(record))
    assert line["msg"] == "hello world" and "fallback" not in line
