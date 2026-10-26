"""At an exact LLM budget limit, deliver the paid result but forbid new requests."""

from pathlib import Path

import pytest

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm.cache import CachedLLMProvider


class FixedUsageProvider:
    max_context_tokens = 512
    max_output_tokens = 1

    def __init__(self, tokens: int):
        self.tokens = tokens
        self.calls = 0
        self.last_usage = {}
        self.total_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    def complete_json(self, *, instructions: str, document_text: str) -> dict:
        self.calls += 1
        self.last_usage = {
            "prompt_tokens": self.tokens - 5,
            "completion_tokens": 5,
            "total_tokens": self.tokens,
        }
        for key, count in self.last_usage.items():
            self.total_usage[key] += count
        return {"ok": True}


@pytest.mark.parametrize("persistent", [False, True])
@pytest.mark.parametrize("limit_kind", ["tokens", "cost"])
def test_exact_request_bound_is_allowed_then_next_request_is_denied(
    tmp_path: Path, persistent: bool, limit_kind: str
) -> None:
    provider = FixedUsageProvider(12)
    options = (
        {"max_reported_tokens": 145}
        if limit_kind == "tokens"
        else {
            "max_estimated_cost_usd": 0.000145,
            "input_cost_usd_per_million_tokens": 1.0,
            "output_cost_usd_per_million_tokens": 1.0,
        }
    )
    cached = CachedLLMProvider(
        provider,
        cache_dir=tmp_path / "cache",
        identity="synthetic",
        ledger_path=tmp_path / "ledger.sqlite" if persistent else None,
        **options,
    )
    assert cached.complete_json(instructions="return JSON", document_text="first") == {"ok": True}
    assert provider.calls == 1
    with pytest.raises(LLMError, match="budget|cost"):
        cached.complete_json(instructions="return JSON", document_text="second")
    assert provider.calls == 1
    # A cached response has no new billable request and remains reusable.
    assert cached.complete_json(instructions="return JSON", document_text="first") == {"ok": True}
    assert provider.calls == 1


@pytest.mark.parametrize("persistent", [False, True])
def test_preflight_upper_bound_over_token_budget_refuses_before_call(
    tmp_path: Path, persistent: bool
) -> None:
    provider = FixedUsageProvider(13)
    cached = CachedLLMProvider(
        provider,
        cache_dir=tmp_path / "cache",
        identity="synthetic",
        ledger_path=tmp_path / "ledger.sqlite" if persistent else None,
        max_reported_tokens=12,
    )
    with pytest.raises(LLMError, match="token budget"):
        cached.complete_json(instructions="return JSON", document_text="first")
    assert provider.calls == 0
    with pytest.raises(LLMError, match="token budget"):
        cached.complete_json(instructions="return JSON", document_text="second")
    assert provider.calls == 0


@pytest.mark.parametrize("persistent", [False, True])
def test_postflight_provider_usage_over_budget_fails_after_request(tmp_path, persistent):
    provider = FixedUsageProvider(146)
    cached = CachedLLMProvider(
        provider,
        cache_dir=tmp_path / "cache",
        identity="synthetic",
        ledger_path=tmp_path / "ledger.sqlite" if persistent else None,
        max_reported_tokens=145,
    )

    with pytest.raises(LLMError, match="token budget"):
        cached.complete_json(instructions="return JSON", document_text="first")

    assert provider.calls == 1


@pytest.mark.parametrize("persistent", [False, True])
@pytest.mark.parametrize("limit_kind", ["tokens", "cost"])
def test_reported_usage_exactly_at_budget_delivers_result_then_denies_next_request(
    tmp_path: Path, persistent: bool, limit_kind: str
) -> None:
    provider = FixedUsageProvider(145)
    options = (
        {"max_reported_tokens": 145}
        if limit_kind == "tokens"
        else {
            "max_estimated_cost_usd": 0.000145,
            "input_cost_usd_per_million_tokens": 1.0,
            "output_cost_usd_per_million_tokens": 1.0,
        }
    )
    cached = CachedLLMProvider(
        provider,
        cache_dir=tmp_path / "cache",
        identity="synthetic",
        ledger_path=tmp_path / "ledger.sqlite" if persistent else None,
        **options,
    )

    assert cached.complete_json(instructions="return JSON", document_text="first") == {"ok": True}
    assert provider.calls == 1
    with pytest.raises(LLMError, match="budget|cost"):
        cached.complete_json(instructions="return JSON", document_text="second")
    assert provider.calls == 1
