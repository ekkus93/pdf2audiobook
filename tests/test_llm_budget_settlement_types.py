"""Fail-closed persistent budget settlement with malformed provider usage."""

import pytest

from pdf2audiobook.errors import LLMError
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
def test_invalid_usage_is_unresolved_and_blocks_new_budgeted_request(tmp_path, usage):
    ledger = BookLLMBudgetLedger(tmp_path / "budget.sqlite3")
    call_id = ledger.reserve(
        request_hash="one", provider_hash="provider",
        max_requests=None, max_tokens=100, max_usd=None,
    )
    ledger.settle(call_id, usage=usage, input_rate=2.0, output_rate=1.0)
    stats = ledger.totals()
    assert stats["requests_started"] == 1
    assert stats["unresolved_requests"] == 1
    assert stats["reported_tokens"] == 0
    with pytest.raises(LLMError, match="unresolved requests"):
        ledger.reserve(
            request_hash="two", provider_hash="provider",
            max_requests=None, max_tokens=100, max_usd=None,
        )


def test_valid_usage_settles_without_undercharging(tmp_path):
    ledger = BookLLMBudgetLedger(tmp_path / "budget.sqlite3")
    call_id = ledger.reserve(
        request_hash="one", provider_hash="provider",
        max_requests=None, max_tokens=100, max_usd=None,
    )
    ledger.settle(
        call_id,
        usage={"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        input_rate=2.0, output_rate=1.0,
    )
    stats = ledger.totals()
    assert stats["requests_started"] == 1
    assert stats["unresolved_requests"] == 0
    assert stats["reported_tokens"] == 30
    assert stats["estimated_cost_usd"] == pytest.approx(0.00005)
