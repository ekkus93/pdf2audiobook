"""LLM provider compatibility, retry and configuration regression coverage."""

import json

import httpx
import pytest

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm import OpenAICompatibleProvider


def make_client(handler, *, temperature=0.1, max_retries=2):
    return OpenAICompatibleProvider(
        provider="llama_server",
        base_url="http://127.0.0.1:8080/v1",
        model="test",
        allow_remote=False,
        temperature=temperature,
        max_retries=max_retries,
        transport=httpx.MockTransport(handler),
    )


def test_unsupported_json_mode_fallback_is_bounded():
    seen = []

    def handler(request):
        payload = json.loads(request.content)
        seen.append(payload)
        if "response_format" in payload:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "response_format is not supported by this server",
                        "param": "response_format",
                    }
                },
            )
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"headings":[]}'}}]})

    with make_client(handler, max_retries=0, temperature=0.25) as client:
        assert client.complete_json(instructions="system", document_text="raw") == {
            "headings": [],
        }
    assert len(seen) == 2
    assert seen[0]["temperature"] == 0.25
    assert "response_format" not in seen[1]


def test_ordinary_bad_request_never_silently_downgrades():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(400, json={"error": {"message": "model not loaded"}})

    with make_client(handler) as client:
        with pytest.raises(LLMError):
            client.complete_json(instructions="x", document_text="y")
    assert len(requests) == 1


def test_rate_limited_request_retried_without_content_loss(monkeypatch):
    monkeypatch.setattr("pdf2audiobook.llm.time.sleep", lambda _: None)
    inputs = []

    def handler(request):
        inputs.append(json.loads(request.content))
        if len(inputs) <= 2:
            return httpx.Response(429, json={"error": "busy"})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"headings":[]}'}}]})

    with make_client(handler) as client:
        assert client.complete_json(instructions="sys", document_text="book") == {
            "headings": [],
        }
    assert len(inputs) == 3
    assert all(req["messages"][1]["content"] == "book" for req in inputs)


def test_exhausted_rate_limit_is_error(monkeypatch):
    monkeypatch.setattr("pdf2audiobook.llm.time.sleep", lambda _: None)
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503, json={"error": "busy"})

    with make_client(handler, max_retries=1) as client:
        with pytest.raises(LLMError):
            client.complete_json(instructions="x", document_text="y")
    assert len(calls) == 2


def test_aborted_generation_server_error_is_retried(monkeypatch):
    monkeypatch.setattr("pdf2audiobook.llm.time.sleep", lambda _: None)
    calls = []
    aborted = {"error": {"message": "prediction aborted, token repeat limit reached"}}

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(500, json=aborted)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"headings":[]}'}}]})

    with make_client(handler) as client:
        assert client.complete_json(instructions="x", document_text="y") == {"headings": []}
    assert len(calls) == 2


def test_persistent_server_error_fails_after_bounded_retries(monkeypatch):
    monkeypatch.setattr("pdf2audiobook.llm.time.sleep", lambda _: None)
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500, json={"error": "private book text"})

    with make_client(handler, max_retries=2) as client:
        with pytest.raises(LLMError) as exc:
            client.complete_json(instructions="x", document_text="y")
    assert len(calls) == 3
    assert "private book text" not in str(exc.value)
