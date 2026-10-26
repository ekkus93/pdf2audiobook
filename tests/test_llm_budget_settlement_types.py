"""Fail-closed persistent budget settlement with malformed provider usage."""

import pytest

from pdf2audiobook.llm.budget import BookLLMBudgetLedger


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        {"prompt_tokens": 10, "completion_tokens": 3},
        {"prompt_tokens": True, "completion_tokens": 2, "total_tokens": 3},
        {"prompt_tokens": -1, "completion_tokens": 2, "total_tokens": 3},
        {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 11},
        {"prompt_tokens": "10", "completion_tokens": 2, "total_tokens": 12},
    ],
)
def test_invalid_usage_becomes_unknown_with_its_bound_recorded(tmp_path, usage):
    ledger = BookLLMBudgetLedger(tmp_path / "budget.sqlite3")
    call_id = ledger.reserve(
        request_hash="one",
        provider_hash="provider",
        max_requests=None,
        max_tokens=100,
        max_usd=None,
        upper_bound_tokens=100,
    )
    ledger.settle(call_id, usage=usage, input_rate=2.0, output_rate=1.0)
    stats = ledger.totals()
    assert stats["requests_started"] == 1
    assert stats["unresolved_requests"] == 1
    assert stats["reported_tokens"] == 100
    assert ledger.rows()[0]["status"] == "unknown"


def test_valid_usage_settles_without_undercharging(tmp_path):
    ledger = BookLLMBudgetLedger(tmp_path / "budget.sqlite3")
    call_id = ledger.reserve(
        request_hash="one",
        provider_hash="provider",
        max_requests=None,
        max_tokens=100,
        max_usd=None,
        upper_bound_tokens=100,
    )
    ledger.settle(
        call_id,
        usage={"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        input_rate=2.0,
        output_rate=1.0,
    )
    stats = ledger.totals()
    assert stats["requests_started"] == 1
    assert stats["unresolved_requests"] == 0
    assert stats["reported_tokens"] == 30
    assert stats["estimated_cost_usd"] == pytest.approx(0.00005)
