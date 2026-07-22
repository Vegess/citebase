def signup(client, email: str, org_name: str = "Acme"):
    return client.post(
        "/auth/signup",
        json={"email": email, "password": "password123", "org_name": org_name},
    )


def login(client, email: str):
    return client.post(
        "/auth/login",
        data={"username": email, "password": "password123"},
        headers={"content-type": "application/x-www-form-urlencoded"},
    )


def test_document_upload_returns_processing_and_status_polling(app_client):
    signup_resp = signup(app_client, "bg@example.com")
    assert signup_resp.status_code == 201
    token = login(app_client, "bg@example.com").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    upload = app_client.post(
        "/documents",
        files={"file": ("doc.txt", b"Test document data.", "text/plain")},
        headers=headers,
    )

    assert upload.status_code == 201
    doc_id = upload.json()["id"]
    assert upload.json()["status"] == "processing"

    status = app_client.get(f"/documents/{doc_id}", headers=headers)
    assert status.status_code == 200
    assert status.json()["id"] == doc_id
    assert status.json()["status"] in {"processing", "ready", "failed"}


def test_chat_streaming_endpoint_returns_sse(app_client):
    signup_resp = signup(app_client, "stream@example.com")
    assert signup_resp.status_code == 201
    token = login(app_client, "stream@example.com").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    upload = app_client.post(
        "/documents",
        files={"file": ("doc.txt", b"Test document data.", "text/plain")},
        headers=headers,
    )
    assert upload.status_code == 201

    with app_client.stream(
        "POST",
        "/chat/ask/stream",
        json={"question": "Stream this"},
        headers=headers,
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        body = b"".join(response.iter_bytes())
        assert b"data: stub" in body
        assert b"data: bed" in body
        assert b"data:  answer" in body
