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

    conversation = app_client.post("/chat/conversations", headers=headers).json()
    conversation_id = conversation["id"]

    first = app_client.post(
        "/chat/ask",
        json={"question": "Hello", "conversation_id": conversation_id},
        headers=headers,
    )
    assert first.status_code == 200

    second = app_client.post(
        "/chat/ask",
        json={"question": "Follow up question", "conversation_id": conversation_id},
        headers=headers,
    )
    assert second.status_code == 200

    from app.services import generation

    assert generation.last_request_messages is not None
    assert any("Hello" in message["content"] for message in generation.last_request_messages)
    assert any("Follow up question" in message["content"] for message in generation.last_request_messages)


def test_cross_org_conversation_access_returns_404(app_client):
    signup(app_client, "owner@example.com", org_name="Alpha")
    owner_token = login(app_client, "owner@example.com").json()["access_token"]
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    signup(app_client, "viewer@example.com", org_name="Beta")
    viewer_token = login(app_client, "viewer@example.com").json()["access_token"]
    viewer_headers = {"Authorization": f"Bearer {viewer_token}"}

    created = app_client.post("/chat/conversations", headers=owner_headers).json()

    response = app_client.get(f"/chat/conversations/{created['id']}", headers=viewer_headers)

    assert response.status_code == 404
