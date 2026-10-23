import json

import httpx
import pytest

from pdf2audiobook.config import Settings
from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm import (
    OpenAICompatibleProvider,
    create_provider,
    detect_llm_headings,
    validate_endpoint,
)
from pdf2audiobook.models import DocumentBlock


def test_privacy_gate_and_tls():
    with pytest.raises(LLMError):
        validate_endpoint("https://example.com/v1", False)
    with pytest.raises(LLMError):
        validate_endpoint("http://example.com/v1", True)
    with pytest.raises(LLMError):
        validate_endpoint("https://user:pw@example.com/v1", True)
    assert validate_endpoint("http://127.0.0.1:11434/v1", False).endswith("/v1")


def test_openai_requires_opt_in_and_key(monkeypatch):
    settings = Settings()
    settings.llm.provider = "openai"
    with pytest.raises(LLMError, match="consent|allow-remote-content"):
        create_provider(settings)
    settings.llm.allow_remote_content = True
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMError, match="API key"):
        create_provider(settings)


@pytest.mark.parametrize("name", ["ollama", "llama-server", "openai"])
def test_json_completion_contract(name):
    def handler(request):
        assert request.url.path.endswith("/chat/completions")
        data = json.loads(request.content)
        assert data["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"headings":[]}'}}]},
        )

    url = "https://api.openai.com/v1" if name == "openai" else "http://localhost:8080/v1"
    with OpenAICompatibleProvider(
        provider=name,
        base_url=url,
        model="mock",
        allow_remote=name == "openai",
        transport=httpx.MockTransport(handler),
    ) as provider:
        assert provider.complete_json(instructions="Classify only", document_text="chapter") == {
            "headings": []
        }


def test_bad_llm_output_is_rejected():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "non-json"}}]})

    with OpenAICompatibleProvider(
        provider="ollama",
        base_url="http://127.0.0.1:11434/v1",
        model="mock",
        allow_remote=False,
        transport=httpx.MockTransport(handler),
    ) as provider:
        with pytest.raises(LLMError):
            provider.complete_json(instructions="x", document_text="y")


def test_llm_does_not_invent_headings():
    class Fake:
        def complete_json(self, **kwargs):
            return {
                "headings": [
                    {"block_id": "b1", "title": "Chapter One", "confidence": 0.9},
                    {"block_id": "invented", "title": "Chapter Two", "confidence": 0.9},
                    {"block_id": "b2", "title": "An invention", "confidence": 0.99},
                ]
            }

    blocks = [
        DocumentBlock(id="b1", page_index=0, text="Chapter One"),
        DocumentBlock(id="b2", page_index=0, text="Actual text"),
    ]
    ids, warnings = detect_llm_headings(blocks, Fake())
    assert ids == {"b1"}
    assert len(warnings) == 2


def test_remote_book_content_warning_precedes_first_upload_only(capsys):
    seen = []

    def handler(request):
        # Observe stderr at the instant the mocked remote upload occurs.
        seen.append(capsys.readouterr().err)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"headings":[]}'}}]})

    with OpenAICompatibleProvider(
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="mock-remote",
        allow_remote=True,
        transport=httpx.MockTransport(handler),
    ) as provider:
        provider.complete_json(instructions="analyse", document_text="PRIVATE_BOOK_TEXT")
        provider.complete_json(instructions="analyse", document_text="PRIVATE_BOOK_TEXT")
    assert len(seen) == 2
    assert "remote LLM" in seen[0]
    assert "openai" in seen[0]
    assert "mock-remote" in seen[0]
    assert "current analysis block window" in seen[0]
    assert "PRIVATE_BOOK_TEXT" not in seen[0]
    assert seen[1] == ""


def test_loopback_model_never_emits_remote_upload_warning(capsys):
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"headings":[]}'}}]})

    with OpenAICompatibleProvider(
        provider="ollama",
        base_url="http://127.0.0.1:11434/v1",
        model="mock-local",
        allow_remote=False,
        transport=httpx.MockTransport(handler),
    ) as provider:
        provider.complete_json(instructions="analyse", document_text="Book text")
    assert "remote LLM" not in capsys.readouterr().err
