import io

import pytest
from fastapi.testclient import TestClient


def signup(client: TestClient, email: str, org_name: str = "Acme"):
    return client.post(
        "/auth/signup",
        json={"email": email, "password": "password123", "org_name": org_name},
    )


def login(client: TestClient, email: str):
    return client.post(
        "/auth/login",
        data={"username": email, "password": "password123"},
        headers={"content-type": "application/x-www-form-urlencoded"},
    )


def test_signup_and_login_success(app_client):
    signup_resp = signup(app_client, "user1@example.com")
    assert signup_resp.status_code == 201
    assert signup_resp.json()["token_type"] == "bearer"

    login_resp = login(app_client, "user1@example.com")
    assert login_resp.status_code == 200
    assert "access_token" in login_resp.json()


def test_signup_and_login_failures(app_client):
    first = signup(app_client, "dup@example.com")
    assert first.status_code == 201

    second = signup(app_client, "dup@example.com")
    assert second.status_code == 409
    assert second.json()["detail"] == "Email already registered"

    bad_login = login(app_client, "missing@example.com")
    assert bad_login.status_code == 401
    assert bad_login.json()["detail"] == "Incorrect email or password"


def test_requests_without_token_return_401(app_client):
    resp = app_client.get("/documents")
    assert resp.status_code == 401


def test_production_hides_docs_and_openapi(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    import app.core.database as database_module
    import app.main as main_module
    import sys

    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            sys.modules.pop(name, None)

    import importlib
    importlib.invalidate_caches()
    main_module = importlib.import_module("app.main")

    assert main_module.app.docs_url is None
    assert main_module.app.redoc_url is None
    assert main_module.app.openapi_url is None


def test_upload_validation_errors(app_client):
    signup_resp = signup(app_client, "uploader@example.com")
    assert signup_resp.status_code == 201
    token = login(app_client, "uploader@example.com").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    bad_type = app_client.post(
        "/documents",
        files={"file": ("notes.json", b'{"bad": true}', "application/json")},
        headers=headers,
    )
    assert bad_type.status_code == 415

    large_payload = b"x" * (21 * 1024 * 1024)
    oversized = app_client.post(
        "/documents",
        files={"file": ("big.txt", large_payload, "text/plain")},
        headers=headers,
    )
    assert oversized.status_code == 413


def test_sql_and_vector_queries_are_org_scoped(app_client):
    org_a = signup(app_client, "orga@example.com", org_name="OrgA")
    org_b = signup(app_client, "orgb@example.com", org_name="OrgB")
    assert org_a.status_code == 201
    assert org_b.status_code == 201

    token_a = login(app_client, "orga@example.com").json()["access_token"]
    token_b = login(app_client, "orgb@example.com").json()["access_token"]

    from app.core.database import SessionLocal
    from app.models.models import Document, Org
    from sqlalchemy import select

    doc_a = app_client.post(
        "/documents",
        files={"file": ("alpha.txt", b"Alpha doc for OrgA.", "text/plain")},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    doc_b = app_client.post(
        "/documents",
        files={"file": ("beta.txt", b"Beta doc for OrgB.", "text/plain")},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert doc_a.status_code == 201
    assert doc_b.status_code == 201

    with SessionLocal() as db:
        org_a_record = db.scalar(select(Org).where(Org.name == "OrgA"))
        org_b_record = db.scalar(select(Org).where(Org.name == "OrgB"))
        sql_rows = db.scalars(select(Document).where(Document.org_id == org_a_record.id)).all()
        assert [row.filename for row in sql_rows] == ["alpha.txt"]
        assert not any(row.org_id == org_b_record.id for row in sql_rows)

    from app.services import rag
    vector_results = rag.retrieve_chunks(org_a_record.id, "doc", top_k=10)
    assert [hit["filename"] for hit in vector_results] == ["alpha.txt"]
    assert rag.retrieve_chunks(org_b_record.id, "Alpha doc for OrgA.", top_k=10)[0]["filename"] == "beta.txt"


def test_document_delete_removes_vector_entries(app_client):
    signup_resp = signup(app_client, "deleter@example.com", org_name="DeleteOrg")
    assert signup_resp.status_code == 201
    token = login(app_client, "deleter@example.com").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    upload_resp = app_client.post(
        "/documents",
        files={"file": ("delete-me.txt", b"This file should disappear after deletion.", "text/plain")},
        headers=headers,
    )
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["id"]

    r1 = app_client.get("/documents", headers=headers)
    assert any(doc["id"] == doc_id and doc["status"] == "ready" and doc["num_chunks"] == 1 for doc in r1.json())

    delete_resp = app_client.delete(f"/documents/{doc_id}", headers=headers)
    assert delete_resp.status_code == 204

    r2 = app_client.get("/documents", headers=headers)
    assert all(doc["id"] != doc_id for doc in r2.json())

    from app.core.database import SessionLocal
    from app.models.models import DocumentChunk, DocumentEvent
    from sqlalchemy import func, select
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.doc_id == doc_id)) == 0
        assert db.scalar(select(func.count()).select_from(DocumentEvent).where(DocumentEvent.doc_id == doc_id)) == 0


def test_org_isolation_blocks_other_org_chunks(app_client):
    user_a = signup(app_client, "usera@example.com", org_name="OrgA")
    user_b = signup(app_client, "userb@example.com", org_name="OrgB")
    assert user_a.status_code == 201
    assert user_b.status_code == 201

    token_a = login(app_client, "usera@example.com").json()["access_token"]
    token_b = login(app_client, "userb@example.com").json()["access_token"]

    upload_resp = app_client.post(
        "/documents",
        files={"file": ("alpha.txt", b"Alpha doc contents for tenant A.", "text/plain")},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert upload_resp.status_code == 201

    chat_resp = app_client.post(
        "/chat/ask",
        json={"question": "What is in the document?"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert chat_resp.status_code == 200
    assert chat_resp.json()["citations"] == []
