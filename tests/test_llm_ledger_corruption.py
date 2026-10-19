"""Malformed SQLite ledger counters must fail closed, not silently sum as zero."""

import sqlite3

import pytest

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm.budget import BookLLMBudgetLedger


@pytest.mark.parametrize("column", ["prompt_tokens", "completion_tokens", "total_tokens"])
@pytest.mark.parametrize("bad_value", ["not-an-integer", 1.25, b"binary-counter"])
def test_corrupt_complete_counter_blocks_reporting_and_reservation(
    tmp_path, column, bad_value,
):
    path = tmp_path / "book-llm.sqlite3"
    ledger = BookLLMBudgetLedger(path)
    assert ledger.totals()["requests_started"] == 0

    counters = {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}
    counters[column] = bad_value
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO calls (request_hash, provider_hash, status, "
            "prompt_tokens, completion_tokens, total_tokens) "
            "VALUES (?, ?, 'complete', ?, ?, ?)",
            ("request", "provider", counters["prompt_tokens"],
             counters["completion_tokens"], counters["total_tokens"]),
        )

    with pytest.raises(LLMError, match="Invalid per-book LLM budget ledger entries"):
        ledger.totals()
    with pytest.raises(LLMError, match="Invalid per-book LLM budget ledger entries"):
        ledger.reserve(
            request_hash="next", provider_hash="provider",
            max_requests=10, max_tokens=100, max_usd=None,
        )
    with pytest.raises(LLMError, match="Invalid per-book LLM budget ledger entries"):
        ledger.check_spend(max_tokens=100, max_usd=None)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 1


def test_corrupt_cost_storage_type_fails_closed(tmp_path):
    path = tmp_path / "book-llm.sqlite3"
    ledger = BookLLMBudgetLedger(path)
    ledger.totals()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO calls (request_hash, provider_hash, status, "
            "prompt_tokens, completion_tokens, total_tokens, estimated_usd) "
            "VALUES ('request', 'provider', 'complete', 2, 3, 5, ?)",
            (sqlite3.Binary(b"\x00\xff"),),
        )
    with pytest.raises(LLMError, match="Invalid per-book LLM budget ledger entries"):
        ledger.totals()


def test_valid_integer_counters_remain_accepted(tmp_path):
    path = tmp_path / "book-llm.sqlite3"
    ledger = BookLLMBudgetLedger(path)
    ledger.totals()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO calls (request_hash, provider_hash, status, "
            "prompt_tokens, completion_tokens, total_tokens, estimated_usd) "
            "VALUES ('request', 'provider', 'complete', 2, 3, 5, '0.0005')"
        )
    stats = ledger.totals()
    assert stats["reported_tokens"] == 5
    assert stats["prompt_tokens"] == 2
    assert stats["completion_tokens"] == 3
    assert stats["estimated_cost_usd"] == 0.0005
