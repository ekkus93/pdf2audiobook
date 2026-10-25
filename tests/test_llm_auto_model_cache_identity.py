"""Automatic served model names participate in request cache identity."""

import pytest

from pdf2audiobook import pipeline
from pdf2audiobook.config import Settings
from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm.budget import BookLLMBudgetLedger
from pdf2audiobook.llm.cache import CachedLLMProvider


class AutoModelStub:
    def __init__(self):
        self.model = "served-a"
        self.calls = 0

    def resolve_model(self):
        return self.model

    def complete_json(self, *, instructions, document_text):
        self.calls += 1
        return {"served": self.model}


def test_changed_served_model_invalidates_cached_response(tmp_path):
    provider = AutoModelStub()
    worker = CachedLLMProvider(provider, cache_dir=tmp_path, identity="provider-auto")
    assert worker.complete_json(instructions="task", document_text="private") == {
        "served": "served-a"
    }
    provider.model = "served-b"
    assert worker.complete_json(instructions="task", document_text="private") == {
        "served": "served-b"
    }
    assert provider.calls == 2


def test_analysis_fingerprint_uses_resolved_model_before_cache_creation(monkeypatch):
    settings = Settings()
    settings.llm.provider = "llama-server"
    settings.llm.llama_server.model = "auto"

    class Context:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def resolve_model(self):
            return "served-model-9b"

    monkeypatch.setattr(pipeline, "create_provider", lambda _settings: Context())
    resolved = pipeline._resolve_auto_llm_model(settings)
    assert resolved.llm.llama_server.model == "served-model-9b"
    assert settings.llm.llama_server.model == "auto"
    assert (
        pipeline._analysis_stage_fingerprints("book-hash", resolved, None)["llm-analysis"]
        != (pipeline._analysis_stage_fingerprints("book-hash", settings, None)["llm-analysis"])
    )


def test_ambiguous_auto_model_resolution_fails_closed(monkeypatch):
    settings = Settings()
    settings.llm.provider = "llama-server"
    settings.llm.llama_server.model = "auto"

    class Context:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def resolve_model(self):
            raise LLMError("Automatic model selection requires exactly one served model")

    monkeypatch.setattr(pipeline, "create_provider", lambda _settings: Context())
    with pytest.raises(LLMError, match="exactly one"):
        pipeline._resolve_auto_llm_model(settings)


def test_model_discovery_failure_does_not_reserve_budget(tmp_path):
    class UnavailableModel:
        def resolve_model(self):
            raise LLMError("Could not discover the served LLM models")

    ledger_path = tmp_path / "ledger.sqlite3"
    worker = CachedLLMProvider(
        UnavailableModel(),
        cache_dir=tmp_path / "cache",
        identity="auto",
        ledger_path=ledger_path,
        max_requests=1,
        max_reported_tokens=100,
    )
    with pytest.raises(LLMError, match="discover"):
        worker.complete_json(instructions="task", document_text="book")
    assert BookLLMBudgetLedger(ledger_path).rows() == []
