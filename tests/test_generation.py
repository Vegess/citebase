from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import app.services.generation as generation
from app.services.generation import generate_answer


@pytest.fixture
def chunks():
    return [
        {"filename": "policy.txt", "chunk_index": 0, "text": "The refund window is 30 days after purchase."}
    ]


def test_generate_answer_falls_back_to_local_context_when_anthropic_is_unavailable(chunks):
    settings = SimpleNamespace(
        llm_provider="anthropic",
        anthropic_api_key=None,
        google_api_key=None,
        gemini_model="gemini-2.0-flash",
        claude_model="claude-sonnet-4-6",
    )

    with patch.object(generation, "settings", settings):
        with patch.object(generation, "get_client", side_effect=RuntimeError("missing anthropic client")):
            answer = generate_answer("What is the refund window?", chunks)

    assert "refund" in answer.lower()
    assert "policy.txt" in answer


def test_generate_answer_fallback_message_mentions_provider_configuration(chunks):
    settings = SimpleNamespace(
        llm_provider="anthropic",
        anthropic_api_key=None,
        google_api_key=None,
        gemini_model="gemini-2.0-flash",
        claude_model="claude-sonnet-4-6",
    )

    with patch.object(generation, "settings", settings):
        with patch.object(generation, "get_client", side_effect=RuntimeError("missing anthropic client")):
            answer = generate_answer("What is the refund window?", chunks)

    assert "active llm provider" in answer.lower()
    assert "configuration" in answer.lower()


def test_generate_answer_uses_gemini_when_configured(chunks):
    settings = SimpleNamespace(
        llm_provider="gemini",
        anthropic_api_key=None,
        google_api_key="google-key",
        gemini_model="gemini-2.0-flash",
        claude_model="claude-sonnet-4-6",
    )
    fake_client = Mock()
    fake_client.models.generate_content.return_value = SimpleNamespace(text="Gemini answer")

    with patch.object(generation, "settings", settings):
        with patch.object(generation, "get_client", return_value=fake_client):
            answer = generate_answer("What is the refund window?", chunks)

    assert answer == "Gemini answer"


def test_generate_answer_uses_groq_when_configured(chunks):
    settings = SimpleNamespace(
        llm_provider="groq",
        groq_api_key="groq-key",
        groq_model="llama-3.3-70b-versatile",
        anthropic_api_key=None,
        google_api_key=None,
        gemini_model="gemini-2.0-flash",
        claude_model="claude-sonnet-4-6",
    )
    fake_client = Mock()
    fake_client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="Groq answer"))]
    )

    with patch.object(generation, "settings", settings):
        with patch.object(generation, "get_client", return_value=fake_client):
            answer = generate_answer("What is the refund window?", chunks)

    assert answer == "Groq answer"
