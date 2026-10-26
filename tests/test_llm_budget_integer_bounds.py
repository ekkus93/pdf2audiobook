"""Persist provider token usage conservatively at SQLite integer limits."""

import pytest

from pdf2audiobook.llm.budget import BookLLMBudgetLedger


@pytest.mark.parametrize(
    "usage",
    [
        {"prompt_tokens": 2**63, "completion_tokens": 0, "total_tokens": 2**63},
        {"prompt_tokens": 0, "completion_tokens": 2**63, "total_tokens": 2**63},
        {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 2**63},
        {"prompt_tokens": 2**63 - 1, "completion_tokens": 1, "total_tokens": 2**63},
    ],
)
def test_out_of_range_provider_usage_becomes_unknown_with_bound_recorded(tmp_path, usage):
    ledger = BookLLMBudgetLedger(tmp_path / "llm.sqlite3")
    call_id = ledger.reserve(
        request_hash="request",
        provider_hash="provider",
        max_requests=None,
        max_tokens=100,
        max_usd=None,
        upper_bound_tokens=100,
    )
    ledger.settle(call_id, usage=usage, input_rate=1.0, output_rate=1.0)
    stats = ledger.totals()
    assert stats["requests_started"] == 1
    assert stats["unresolved_requests"] == 1
    assert stats["reported_tokens"] == 100
    assert ledger.rows()[0]["status"] == "unknown"


def test_valid_provider_usage_remains_accounted(tmp_path):
    ledger = BookLLMBudgetLedger(tmp_path / "llm.sqlite3")
    call_id = ledger.reserve(
        request_hash="request",
        provider_hash="provider",
        max_requests=None,
        max_tokens=100,
        max_usd=None,
        upper_bound_tokens=100,
    )
    ledger.settle(
        call_id,
        usage={"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        input_rate=1.0,
        output_rate=1.0,
    )
    stats = ledger.totals()
    assert stats["requests_started"] == 1
    assert stats["unresolved_requests"] == 0
    assert stats["reported_tokens"] == 5
    assert stats["prompt_tokens"] == 2
    assert stats["completion_tokens"] == 3
