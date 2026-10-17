"""Cached LLM adapter preserves the public provider discovery contract."""

import pytest

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm import LLMProvider
from pdf2audiobook.llm.cache import CachedLLMProvider


class DiscoveryProvider:
    def __init__(self):
        self.discovery_calls = 0
        self.health_calls = 0
        self.completion_calls = 0

    def list_models(self):
        self.discovery_calls += 1
        return ["synthetic-model"]

    def health(self):
        self.health_calls += 1
        return True

    def complete_json(self, *, instructions, document_text):
        self.completion_calls += 1
        return {"ok": True}


def test_cache_wrapper_exposes_discovery_and_health_without_upload(tmp_path):
    underlying = DiscoveryProvider()
    cached = CachedLLMProvider(
        underlying, cache_dir=tmp_path / "cache", identity="synthetic",
    )
    assert isinstance(cached, LLMProvider)
    assert cached.list_models() == ["synthetic-model"]
    assert cached.health() is True
    assert underlying.discovery_calls == 1
    assert underlying.health_calls == 1
    assert underlying.completion_calls == 0


def test_cache_wrapper_fails_closed_for_missing_discovery(tmp_path):
    cached = CachedLLMProvider(
        object(), cache_dir=tmp_path / "cache", identity="synthetic",
    )
    assert cached.health() is False
    with pytest.raises(LLMError, match="model discovery"):
        cached.list_models()


@pytest.mark.parametrize("bad", [None, "model", [1, "model"], {"data": []}])
def test_cache_wrapper_rejects_invalid_model_list(tmp_path, bad):
    class InvalidProvider:
        def list_models(self):
            return bad

    cached = CachedLLMProvider(
        InvalidProvider(), cache_dir=tmp_path / "cache", identity="synthetic",
    )
    with pytest.raises(LLMError, match="Invalid LLM provider model discovery"):
        cached.list_models()
