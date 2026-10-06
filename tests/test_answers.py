"""Sprint 1: citations point only at sources the answer used; chats get titles."""
from app.services.citations import select_citations

CHUNKS = [
    {"filename": "resume.pdf", "chunk_index": 6, "text": "a"},
    {"filename": "resume.pdf", "chunk_index": 9, "text": "b"},
    {"filename": "handbook.pdf", "chunk_index": 2, "text": "c"},
]


def test_only_cited_sources_are_returned():
    used = select_citations("Notice is 30 days [3]. Probation is 7 days [3].", CHUNKS)
    assert used == [{"filename": "handbook.pdf", "chunk_index": 2, "n": 3}]


def test_grouped_markers_and_out_of_range_numbers():
    used = select_citations("Both apply [1, 2]. Ignore [7] and [0].", CHUNKS)
    assert [c["n"] for c in used] == [1, 2]


def test_abstention_carries_no_sources():
    # The exact failure from the live screenshot: a refusal that still showed 3 sources.
    answer = ("I'm unable to review or rate the document because it hasn't been "
              "provided in the excerpts available to me.")
    assert select_citations(answer, CHUNKS) == []
    assert select_citations("Your documents don't mention a dress code.", CHUNKS) == []


def test_answer_without_markers_keeps_all_sources():
    used = select_citations("The notice period is 30 days.", CHUNKS)
    assert [c["n"] for c in used] == [1, 2, 3]


def _signup(client):
    token = client.post("/auth/signup", json={
        "email": "t@acme.com", "password": "password123", "org_name": "Acme"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_first_question_names_a_precreated_conversation(app_client):
    headers = _signup(app_client)
    convo = app_client.post("/chat/conversations", headers=headers).json()
    assert convo["title"] == "New conversation"

    app_client.post("/chat/ask", headers=headers,
                    json={"question": "  What is the   leave policy? ", "conversation_id": convo["id"]})
    app_client.post("/chat/ask", headers=headers,
                    json={"question": "And for interns?", "conversation_id": convo["id"]})

    titles = [c["title"] for c in app_client.get("/chat/conversations", headers=headers).json()]
    assert titles == ["What is the leave policy?"]


def test_streamed_first_question_names_the_conversation(app_client):
    headers = _signup(app_client)
    convo = app_client.post("/chat/conversations", headers=headers).json()
    with app_client.stream("POST", "/chat/ask/stream", headers=headers,
                           json={"question": "Summarise the travel policy", "conversation_id": convo["id"]}) as r:
        b"".join(r.iter_bytes())
    assert app_client.get("/chat/conversations", headers=headers).json()[0]["title"] == "Summarise the travel policy"


def test_long_question_titles_are_trimmed(app_client):
    headers = _signup(app_client)
    app_client.post("/chat/ask", headers=headers, json={"question": "x" * 300})
    title = app_client.get("/chat/conversations", headers=headers).json()[0]["title"]
    assert len(title) == 80 and title.endswith("...")
