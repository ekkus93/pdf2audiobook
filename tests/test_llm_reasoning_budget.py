"""Reasoning models must not silently spend the whole output cap on hidden thinking."""

from __future__ import annotations

import json

import httpx
import pytest

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm import OpenAICompatibleProvider

PROVIDERS = ("openai", "ollama", "llama-server")
SENTINEL = "PRIVATE_SYNTHETIC_REASONING_TEXT_77"


def _provider(name, handler):
    url = "https://api.openai.com/v1" if name == "openai" else "http://127.0.0.1:11434/v1"
    return OpenAICompatibleProvider(
        provider=name,
        base_url=url,
        model="mock",
        allow_remote=name == "openai",
        max_retries=0,
        max_context_tokens=16384,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize("name", PROVIDERS)
def test_reasoning_disabled_only_for_ollama(name):
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}}]})

    with _provider(name, handler) as provider:
        assert provider.complete_json(instructions="x", document_text="y") == {"ok": True}
    assert seen["max_tokens"] == 1024
    if name == "ollama":
        assert seen["reasoning_effort"] == "none"
    else:
        assert "reasoning_effort" not in seen


@pytest.mark.parametrize("name", PROVIDERS)
@pytest.mark.parametrize("content", ["", "   ", None])
def test_output_cap_exhausted_by_reasoning_has_actionable_error(name, content):
    def handler(request):
        message = {"content": content, "reasoning": f"thinking about {SENTINEL}"}
        return httpx.Response(
            200,
            json={
                "choices": [{"message": message, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 37, "completion_tokens": 1024, "total_tokens": 1061},
            },
        )

    with _provider(name, handler) as provider:
        with pytest.raises(LLMError, match="output cap reached") as raised:
            provider.complete_json(instructions="x", document_text="y")
        # Billable usage is still accounted for the failed reply.
        assert provider.last_usage["completion_tokens"] == 1024
    assert SENTINEL not in str(raised.value)
    assert raised.value.__cause__ is None


@pytest.mark.parametrize("name", PROVIDERS)
def test_answer_cut_off_at_output_cap_has_actionable_error(name):
    def handler(request):
        content = '{"edits":[{"original":"' + SENTINEL
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}, "finish_reason": "length"}]},
        )

    with _provider(name, handler) as provider:
        with pytest.raises(LLMError, match="cut off at the output cap") as raised:
            provider.complete_json(instructions="x", document_text="y")
    assert SENTINEL not in str(raised.value)
    assert raised.value.__cause__ is None


def test_malformed_complete_answer_still_reports_decoding_failure():
    def handler(request):
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ok":'}, "finish_reason": "stop"}]},
        )

    with _provider("ollama", handler) as provider:
        with pytest.raises(LLMError, match="decoding failed"):
            provider.complete_json(instructions="x", document_text="y")
