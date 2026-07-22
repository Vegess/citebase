from app.models.schemas import AskRequest


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


def test_chat_uses_conversation_memory(app_client):
    signup_resp = signup(app_client, "memory@example.com")
    assert signup_resp.status_code == 201
    token = login(app_client, "memory@example.com").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    upload = app_client.post(
        "/documents",
        files={"file": ("memory.txt", b"A helpful memory document for question answering.", "text/plain")},
        headers=headers,
    )
    assert upload.status_code == 201

    first = app_client.post("/chat/ask", json={"question": "Hello"}, headers=headers)
    assert first.status_code == 200

    second = app_client.post("/chat/ask", json={"question": "Follow up question"}, headers=headers)
    assert second.status_code == 200

    from app.services import generation

    assert generation.last_request_messages is not None
    assert any("Hello" in message["content"] for message in generation.last_request_messages)
    assert any("Follow up question" in message["content"] for message in generation.last_request_messages)
