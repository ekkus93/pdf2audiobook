"""Offline provider contract matrix for OpenAI, Ollama and llama-server."""

from __future__ import annotations

import json

import httpx
import pytest

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm import OpenAICompatibleProvider, detect_llm_headings
from pdf2audiobook.models import DocumentBlock

PROVIDERS = ("openai", "ollama", "llama-server")


def _provider(name, handler, *, retries=0, context=None):
    url = "https://api.openai.com/v1" if name == "openai" else ("http://127.0.0.1:11434/v1")
    return OpenAICompatibleProvider(
        provider=name,
        base_url=url,
        model="mock",
        allow_remote=name == "openai",
        max_retries=retries,
        max_context_tokens=context,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize("name", PROVIDERS)
def test_successful_json_contract(name):
    def handler(request):
        payload = json.loads(request.content)
        assert payload["model"] == "mock"
        assert [m["role"] for m in payload["messages"]] == ["system", "user"]
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"headings":[]}'}}]})

    with _provider(name, handler) as provider:
        assert provider.complete_json(
            instructions="Classify", document_text="Untrusted book text"
        ) == {"headings": []}


@pytest.mark.parametrize("name", PROVIDERS)
@pytest.mark.parametrize("bad_content", ["not-json", '{"headings":['])
def test_invalid_or_truncated_json_is_rejected(name, bad_content):
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": bad_content}}]})

    with _provider(name, handler) as provider:
        with pytest.raises(LLMError, match="decoding failed"):
            provider.complete_json(instructions="x", document_text="y")


@pytest.mark.parametrize("name", PROVIDERS)
def test_api_error_is_sanitized(name):
    def handler(request):
        return httpx.Response(500, json={"error": "secret book content and bearer token"})

    with _provider(name, handler) as provider:
        with pytest.raises(LLMError) as exc:
            provider.complete_json(instructions="x", document_text="y")
    assert "secret book content" not in str(exc.value)
    assert "bearer token" not in str(exc.value)


@pytest.mark.parametrize("name", PROVIDERS)
def test_timeout_is_bounded_and_sanitized(name):
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ReadTimeout("private book text")

    with _provider(name, handler, retries=1) as provider:
        with pytest.raises(LLMError, match="transport failure") as exc:
            provider.complete_json(instructions="x", document_text="y")
    assert len(calls) == 2
    assert "private book text" not in str(exc.value)


@pytest.mark.parametrize("name", PROVIDERS)
def test_json_mode_rejection_falls_back_once(name):
    formats = []

    def handler(request):
        payload = json.loads(request.content)
        formats.append(payload.get("response_format"))
        if len(formats) == 1:
            return httpx.Response(400, json={"error": {"message": "response_format unsupported"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"headings":[]}'}}]})

    with _provider(name, handler) as provider:
        assert provider.complete_json(instructions="x", document_text="y") == {"headings": []}
    assert formats == [{"type": "json_object"}, None]


@pytest.mark.parametrize("parameter", ["max_tokens", "temperature"])
@pytest.mark.parametrize("name", PROVIDERS)
def test_rejected_generation_parameter_is_removed_and_remembered(parameter, name):
    seen = []

    def handler(request):
        payload = json.loads(request.content)
        seen.append(parameter in payload)
        if parameter in payload:
            return httpx.Response(
                400,
                json={"error": {"message": f"{parameter} unsupported", "param": parameter}},
            )
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    with _provider(name, handler, context=4096) as provider:
        assert provider.complete_json(instructions="x", document_text="y") == {}
        assert provider.complete_json(instructions="x", document_text="z") == {}
    assert seen == [True, False, False]


@pytest.mark.parametrize("name", PROVIDERS)
def test_schema_incompatibility_rejected_by_structure_verifier(name):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"headings":[{"block_id":"b1","title":"Chapter",'
                            '"confidence":"not-a-number"}]}'
                        }
                    }
                ]
            },
        )

    with _provider(name, handler) as provider:
        accepted, warnings = detect_llm_headings(
            [DocumentBlock(id="b1", page_index=0, text="Chapter")],
            provider,
        )
    assert not accepted
    assert any("rejected" in warning for warning in warnings)
