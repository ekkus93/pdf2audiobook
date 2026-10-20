"""LLM transport and decoding errors cannot reveal third-party diagnostics."""

import httpx
import pytest

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm import OpenAICompatibleProvider

PRIVATE = "SYNTHETIC_PRIVATE_PROVIDER_ERROR_139"


@pytest.mark.parametrize("failure", ["transport", "status", "invalid_json"])
def test_completion_errors_hide_backend_and_server_details(failure: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "transport":
            raise httpx.ConnectError(f"secret local diagnostic {PRIVATE}", request=request)
        if failure == "status":
            return httpx.Response(401, text=PRIVATE)
        return httpx.Response(200, text=PRIVATE)

    with OpenAICompatibleProvider(
        provider="ollama", base_url="http://127.0.0.1:11434/v1",
        model="offline-test", allow_remote=False, max_retries=0,
        transport=httpx.MockTransport(handler),
    ) as provider:
        with pytest.raises(LLMError) as raised:
            provider.complete_json(instructions="system", document_text="synthetic")
    assert PRIVATE not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


def test_discovery_error_suppresses_raw_transport_context() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"discovery text {PRIVATE}", request=request)

    with OpenAICompatibleProvider(
        provider="ollama", base_url="http://127.0.0.1:11434/v1",
        model="offline-test", allow_remote=False,
        transport=httpx.MockTransport(handler),
    ) as provider:
        with pytest.raises(LLMError, match="Could not discover") as raised:
            provider.list_models()
    assert PRIVATE not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


def test_untrusted_direct_provider_label_is_not_echoed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"private diagnostic {PRIVATE}", request=request)

    with OpenAICompatibleProvider(
        provider=PRIVATE, base_url="http://127.0.0.1:11434/v1",
        model="offline-test", allow_remote=False, max_retries=0,
        transport=httpx.MockTransport(handler),
    ) as provider:
        with pytest.raises(LLMError) as raised:
            provider.complete_json(instructions="system", document_text="synthetic")
    assert str(raised.value) == "provider LLM transport failure"
    assert PRIVATE not in str(raised.value)
    assert raised.value.__cause__ is None
