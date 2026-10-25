"""LLM budget prices and persisted entries fail closed on corrupted metadata."""

import sqlite3

import pytest

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm.budget import BookLLMBudgetLedger


@pytest.mark.parametrize("rate", [float("nan"), float("inf"), float("-inf"), -1.0])
def test_invalid_token_rates_are_unpriced_not_trusted(tmp_path, rate):
    ledger = BookLLMBudgetLedger(tmp_path / "ledger.sqlite3")
    call_id = ledger.reserve(
        request_hash="case",
        provider_hash="provider",
        max_requests=None,
        max_tokens=None,
        max_usd=0.01,
        upper_bound_usd="0.00001",
    )
    ledger.settle(
        call_id,
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        input_rate=rate,
        output_rate=1.0,
    )
    stats = ledger.totals()
    assert stats["reported_tokens"] == 15
    assert stats["requests_started"] == 1
    assert stats["unresolved_requests"] == 0
    assert stats["unpriced_requests"] == 1
    assert stats["estimated_cost_usd"] == 0
    with pytest.raises(LLMError, match="unpriced earlier requests"):
        ledger.reserve(
            request_hash="next",
            provider_hash="provider",
            max_requests=None,
            max_tokens=None,
            max_usd=0.01,
            upper_bound_usd="0.00001",
        )


@pytest.mark.parametrize("bad_status", ["pending", "unknown"])
def test_corrupt_unsettled_entries_with_usage_are_rejected(tmp_path, bad_status):
    ledger = BookLLMBudgetLedger(tmp_path / "ledger.sqlite3")
    call_id = ledger.reserve(
        request_hash="case",
        provider_hash="provider",
        max_requests=None,
        max_tokens=None,
        max_usd=None,
    )
    with sqlite3.connect(ledger.path) as conn:
        conn.execute(
            "UPDATE calls SET status=?, total_tokens=100 WHERE id=?",
            (bad_status, call_id),
        )
    with pytest.raises(LLMError, match="Invalid per-book LLM budget ledger entries"):
        ledger.totals()
    with pytest.raises(LLMError, match="Invalid per-book LLM budget ledger entries"):
        ledger.reserve(
            request_hash="next",
            provider_hash="provider",
            max_requests=None,
            max_tokens=None,
            max_usd=None,
        )


def test_valid_zero_pricing_is_permitted(tmp_path):
    ledger = BookLLMBudgetLedger(tmp_path / "ledger.sqlite3")
    call_id = ledger.reserve(
        request_hash="case",
        provider_hash="provider",
        max_requests=None,
        max_tokens=None,
        max_usd=0.01,
        upper_bound_usd="0.00001",
    )
    ledger.settle(
        call_id,
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        input_rate=0.0,
        output_rate=0.0,
    )
    stats = ledger.totals()
    assert stats["unpriced_requests"] == 0
    assert stats["estimated_cost_usd"] == 0
    assert stats["reported_tokens"] == 15
