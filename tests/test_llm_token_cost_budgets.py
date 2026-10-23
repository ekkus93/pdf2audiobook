"""Provider-reported post-response token and user-priced dollar budgets."""

import json

import pytest

from pdf2audiobook.config import load_settings
from pdf2audiobook.errors import ConfigError, LLMError
from pdf2audiobook.llm.cache import CachedLLMProvider


class Metered:
    def __init__(self):
        self.calls = 0
        self.total_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        self.last_usage = {}

    def complete_json(self, *, instructions, document_text):
        self.calls += 1
        self.last_usage = {
            "prompt_tokens": 40,
            "completion_tokens": 10,
            "total_tokens": 50,
        }
        for key, value in self.last_usage.items():
            self.total_usage[key] += value
        return {"headings": []}


def test_reported_token_limit_blocks_future_requests_and_fails_overshoot(tmp_path):
    provider = Metered()
    worker = CachedLLMProvider(
        provider,
        cache_dir=tmp_path / "cache",
        identity="model",
        max_reported_tokens=70,
        usage_report=tmp_path / "usage.json",
    )
    worker.complete_json(instructions="task", document_text="Private source A")
    with pytest.raises(LLMError, match="token budget"):
        worker.complete_json(instructions="task", document_text="Private source B")
    with pytest.raises(LLMError, match="token budget"):
        worker.complete_json(instructions="task", document_text="Private source C")
    assert provider.calls == 2
    assert len(list((tmp_path / "cache").glob("*.json"))) == 1
    report = json.loads((tmp_path / "usage.json").read_text())
    assert report["provider_reported_tokens"]["total_tokens"] == 100
    assert report["requests_started"] == 2
    assert report["max_reported_tokens"] == 70
    assert "Private source" not in str(report)


def test_priced_cost_limit_uses_reported_usage_and_explicit_rates(tmp_path):
    provider = Metered()
    worker = CachedLLMProvider(
        provider,
        cache_dir=tmp_path / "cache",
        identity="model",
        max_estimated_cost_usd=0.00009,
        input_cost_usd_per_million_tokens=2,
        output_cost_usd_per_million_tokens=1,
        usage_report=tmp_path / "usage.json",
    )
    assert worker.complete_json(instructions="task", document_text="Private source") == {
        "headings": []
    }
    with pytest.raises(LLMError, match="cost budget"):
        worker.complete_json(instructions="task", document_text="Another source")
    assert provider.calls == 1
    record = json.loads((tmp_path / "usage.json").read_text())
    assert record["usage_verified"] is True
    assert record["estimated_cost_usd"] == pytest.approx(0.00009)
    assert len(list((tmp_path / "cache").glob("*.json"))) == 1


def test_missing_telemetry_fails_closed_when_token_limit_is_enabled(tmp_path):
    class Silent:
        def __init__(self):
            self.calls = 0

        def complete_json(self, *, instructions, document_text):
            self.calls += 1
            return {"headings": []}

    provider = Silent()
    worker = CachedLLMProvider(
        provider,
        cache_dir=tmp_path,
        identity="model",
        max_reported_tokens=100,
    )
    with pytest.raises(LLMError, match="requires provider-reported usage"):
        worker.complete_json(instructions="task", document_text="source")
    assert provider.calls == 1
    assert not list(tmp_path.glob("*.json"))


def test_cost_budget_must_have_user_configured_prices():
    with pytest.raises(ConfigError, match="requires explicit input/output"):
        load_settings(
            no_config=True,
            environ={"PDF2AUDIOBOOK_LLM_MAX_ESTIMATED_COST_USD": "1"},
        )
    loaded, sources = load_settings(
        no_config=True,
        environ={"PDF2AUDIOBOOK_LLM_MAX_REPORTED_TOKENS": "150"},
    )
    assert loaded.llm.max_reported_tokens == 150
    assert sources["llm.max_reported_tokens"].startswith("env:")
