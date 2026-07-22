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
