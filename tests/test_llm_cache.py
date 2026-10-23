"""Cache requests by full content, prompt schema and provider identity."""

import json

import pytest

from pdf2audiobook.llm.cache import CachedLLMProvider
from pdf2audiobook.workspace import fingerprint


class Stub:
    def __init__(self):
        self.calls = 0

    def complete_json(self, *, instructions, document_text):
        self.calls += 1
        return {"headings": []}


def test_cache_key_includes_content_prompt_and_provider(tmp_path):
    original = Stub()
    worker = CachedLLMProvider(original, cache_dir=tmp_path, identity="model-v1")
    first = worker.complete_json(instructions="schema1", document_text="Book text")
    assert worker.complete_json(instructions="schema1", document_text="Book text") == first
    assert original.calls == 1
    worker.complete_json(instructions="schema2", document_text="Book text")
    worker.complete_json(instructions="schema1", document_text="Other book")
    CachedLLMProvider(original, cache_dir=tmp_path, identity="model-v2").complete_json(
        instructions="schema1", document_text="Book text"
    )
    assert original.calls == 4
    assert worker.hits == 1
    assert len(list(tmp_path.glob("*.json"))) == 4
    assert all("Book text" not in p.name for p in tmp_path.glob("*.json"))


def test_corruption_and_forged_fingerprint_cause_regeneration(tmp_path):
    provider = Stub()
    worker = CachedLLMProvider(provider, cache_dir=tmp_path, identity="model")
    worker.complete_json(instructions="prompt", document_text="source")
    path = next(tmp_path.glob("*.json"))
    path.write_text("corrupt JSON")
    worker.complete_json(instructions="prompt", document_text="source")
    assert provider.calls == 2
    data = json.loads(path.read_text())
    assert data["fingerprint"] == fingerprint("llm-json-cache-v1", "model", "prompt", "source")
    data["fingerprint"] = "forged"
    path.write_text(json.dumps(data))
    worker.complete_json(instructions="prompt", document_text="source")
    assert provider.calls == 3


def test_disabled_cache_and_failed_response_are_not_persisted(tmp_path):
    provider = Stub()
    worker = CachedLLMProvider(
        provider,
        cache_dir=tmp_path,
        identity="model",
        enabled=False,
    )
    worker.complete_json(instructions="prompt", document_text="source")
    worker.complete_json(instructions="prompt", document_text="source")
    assert provider.calls == 2
    assert not list(tmp_path.glob("*.json"))

    class Failure:
        def complete_json(self, *, instructions, document_text):
            raise RuntimeError("backend failed")

    with pytest.raises(RuntimeError, match="backend failed"):
        CachedLLMProvider(
            Failure(),
            cache_dir=tmp_path,
            identity="model",
        ).complete_json(instructions="prompt", document_text="source")
    assert not list(tmp_path.glob("*.json"))


def test_request_budget_counts_misses_but_allows_cache_hits(tmp_path):
    from pdf2audiobook.errors import LLMError

    source = "Private book passage"
    report = tmp_path / "reports" / "llm_usage.json"
    provider = Stub()
    worker = CachedLLMProvider(
        provider,
        cache_dir=tmp_path / "cache",
        identity="model",
        max_requests=1,
        usage_report=report,
    )
    assert worker.complete_json(instructions="classify", document_text=source) == {"headings": []}
    assert worker.complete_json(instructions="classify", document_text=source) == {"headings": []}
    with pytest.raises(LLMError, match="request budget exhausted"):
        worker.complete_json(instructions="classify", document_text="Different passage")
    assert provider.calls == 1
    record = json.loads(report.read_text(encoding="utf-8"))
    assert record["requests_started"] == 1
    assert record["cache_hits"] == 1
    assert record["cache_misses"] == 2
    assert record["max_requests"] == 1
    assert source not in report.read_text(encoding="utf-8")
    assert "classify" not in report.read_text(encoding="utf-8")


def test_request_budget_counts_failed_provider_attempts(tmp_path):
    from pdf2audiobook.errors import LLMError

    class FailingProvider:
        def __init__(self):
            self.calls = 0

        def complete_json(self, *, instructions, document_text):
            self.calls += 1
            raise LLMError("offline")

    provider = FailingProvider()
    worker = CachedLLMProvider(
        provider,
        cache_dir=tmp_path / "cache",
        identity="model",
        enabled=False,
        max_requests=1,
        usage_report=tmp_path / "usage.json",
    )
    with pytest.raises(LLMError, match="offline"):
        worker.complete_json(instructions="x", document_text="secret")
    with pytest.raises(LLMError, match="request budget exhausted"):
        worker.complete_json(instructions="x", document_text="secret")
    assert provider.calls == 1
    assert json.loads((tmp_path / "usage.json").read_text())["requests_started"] == 1


def test_request_budget_config_env_and_validation():
    from pdf2audiobook.config import load_settings
    from pdf2audiobook.errors import ConfigError

    settings, sources = load_settings(
        no_config=True,
        environ={"PDF2AUDIOBOOK_LLM_MAX_REQUESTS": "2"},
    )
    assert settings.llm.max_requests == 2
    assert sources["llm.max_requests"] == "env:PDF2AUDIOBOOK_LLM_MAX_REQUESTS"
    with pytest.raises(ConfigError, match="invalid configuration values"):
        load_settings(
            no_config=True,
            environ={"PDF2AUDIOBOOK_LLM_MAX_REQUESTS": "0"},
        )


def test_cached_provider_identity_invalidates_on_output_token_cap_change(tmp_path):
    from pdf2audiobook.config import Settings
    from pdf2audiobook.pipeline import _llm_cache_identity

    provider = Stub()
    settings = Settings()
    first_identity = _llm_cache_identity(settings)
    CachedLLMProvider(
        provider,
        cache_dir=tmp_path,
        identity=first_identity,
    ).complete_json(instructions="schema", document_text="text")
    settings.llm.max_output_tokens = 256
    updated_identity = _llm_cache_identity(settings)
    assert first_identity != updated_identity
    CachedLLMProvider(
        provider,
        cache_dir=tmp_path,
        identity=updated_identity,
    ).complete_json(instructions="schema", document_text="text")
    assert provider.calls == 2
    CachedLLMProvider(
        provider,
        cache_dir=tmp_path,
        identity=updated_identity,
    ).complete_json(instructions="schema", document_text="text")
    assert provider.calls == 2
