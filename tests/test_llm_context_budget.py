"""Fail-closed context budgeting for OpenAI-compatible chat requests."""

import json

import httpx
import pytest

from pdf2audiobook.config import Settings, load_settings
from pdf2audiobook.errors import ConfigError, LLMError
from pdf2audiobook.llm import create_provider


@pytest.mark.parametrize("provider_name", ["ollama", "llama-server"])
def test_chat_context_budget_reserves_output_and_caps_response(provider_name):
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"headings":[]}'}}]}
        )

    settings = Settings()
    settings.llm.provider = provider_name
    if provider_name == "llama-server":
        settings.llm.llama_server.model = "mock"
    settings.llm.max_context_tokens = 512
    settings.llm.max_output_tokens = 128
    with create_provider(settings, transport=httpx.MockTransport(handler)) as provider:
        assert provider.complete_json(instructions="i" * 240, document_text="d" * 10) == {
            "headings": []
        }
        assert seen[0]["max_tokens"] == 128
        with pytest.raises(LLMError, match="context"):
            provider.complete_json(instructions="i" * 240, document_text="d" * 17)
    assert len(seen) == 1


def test_non_ascii_document_budget_is_measured_before_network():
    def forbidden(request):
        pytest.fail("oversized request must never reach a provider")

    settings = Settings()
    settings.llm.max_context_tokens = 512
    settings.llm.max_output_tokens = 128
    with create_provider(settings, transport=httpx.MockTransport(forbidden)) as provider:
        with pytest.raises(LLMError, match="context"):
            provider.complete_json(instructions="instruction", document_text="🦋" * 65)


def test_context_reserve_validation_and_environment_override():
    with pytest.raises(ConfigError, match="no context room"):
        load_settings(
            no_config=True,
            overrides={"llm": {
                "max_context_tokens": 512, "chunk_tokens": 100, "max_output_tokens": 384
            }},
        )
    settings, sources = load_settings(
        no_config=True, environ={"PDF2AUDIOBOOK_LLM_MAX_OUTPUT_TOKENS": "256"}
    )
    assert settings.llm.max_output_tokens == 256
    assert sources["llm.max_output_tokens"] == "env:PDF2AUDIOBOOK_LLM_MAX_OUTPUT_TOKENS"
