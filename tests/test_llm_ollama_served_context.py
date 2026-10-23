"""Ollama silently truncates prompts beyond its served context; refuse them first."""

import json

import httpx
import pytest

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm import OpenAICompatibleProvider

pytestmark = pytest.mark.ollama_context

ANSWER = {"choices": [{"message": {"content": '{"headings":[]}'}}]}


def server(context_length, seen, *, name="qwen35-128k:latest"):
    def handler(request):
        seen.append(request.url.path)
        if request.url.path == "/api/generate":
            assert json.loads(request.content)["prompt"] == ""  # load only, no book text
            return httpx.Response(200, json={"done": True})
        if request.url.path == "/api/ps":
            models = [{"name": name, "model": name, "context_length": context_length}]
            return httpx.Response(200, json={"models": models})
        return httpx.Response(200, json=ANSWER)

    return handler


def provider(handler, *, model="qwen35-128k", max_context_tokens=16384):
    return OpenAICompatibleProvider(
        provider="ollama",
        base_url="http://127.0.0.1:11434/v1",
        model=model,
        allow_remote=False,
        transport=httpx.MockTransport(handler),
        max_context_tokens=max_context_tokens,
        max_output_tokens=1024,
    )


def test_request_within_the_served_context_is_sent_and_lookup_is_cached():
    seen = []
    with provider(server(131072, seen)) as client:
        for _ in range(2):
            assert client.complete_json(instructions="x", document_text="y" * 4000) == {
                "headings": []
            }
    assert seen == ["/api/generate", "/api/ps", "/v1/chat/completions", "/v1/chat/completions"]


def test_served_context_smaller_than_the_budget_refuses_before_upload():
    seen = []
    # A 4096-token runner would silently drop the start of this request.
    with provider(server(4096, seen, name="qwen3.5:9b"), model="qwen3.5:9b") as client:
        with pytest.raises(LLMError, match="context length the Ollama server serves"):
            client.complete_json(instructions="x", document_text="PRIVATE " * 600)
    assert "/v1/chat/completions" not in seen


@pytest.mark.parametrize(
    "ps_reply",
    [
        httpx.Response(404, text="not found"),
        httpx.Response(200, json={"models": []}),
        httpx.Response(200, json={"models": [{"name": "other:latest", "context_length": 9}]}),
        httpx.Response(200, json={"models": [{"name": "m:latest", "context_length": True}]}),
        httpx.Response(200, text="not json"),
    ],
)
def test_unknown_served_context_fails_closed_without_uploading(ps_reply):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.path == "/api/ps":
            return ps_reply
        return httpx.Response(200, json={"done": True} if "api" in request.url.path else ANSWER)

    with provider(handler, model="m") as client:
        with pytest.raises(LLMError, match="Could not read the context length"):
            client.complete_json(instructions="x", document_text="PRIVATE book text")
    assert "/v1/chat/completions" not in seen


def test_other_providers_never_query_ollama_endpoints():
    seen = []
    with OpenAICompatibleProvider(
        provider="llama-server",
        base_url="http://127.0.0.1:8080/v1",
        model="m",
        allow_remote=False,
        transport=httpx.MockTransport(server(16, seen)),
    ) as client:
        client.complete_json(instructions="x", document_text="y")
    assert seen == ["/v1/chat/completions"]


def test_cached_rerun_needs_no_running_ollama(tmp_path):
    from pdf2audiobook.llm.cache import CachedLLMProvider

    seen = []
    with provider(server(131072, seen)) as live:
        CachedLLMProvider(live, cache_dir=tmp_path, identity="i").complete_json(
            instructions="x", document_text="y"
        )

    def offline(request):
        raise httpx.ConnectError("server is down")

    with provider(offline) as down:
        cached = CachedLLMProvider(down, cache_dir=tmp_path, identity="i")
        assert cached.complete_json(instructions="x", document_text="y") == {"headings": []}
        with pytest.raises(LLMError, match="Could not read the context length"):
            cached.complete_json(instructions="x", document_text="uncached")
