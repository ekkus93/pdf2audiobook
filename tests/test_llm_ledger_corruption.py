"""Fail-closed regression for tampered persistent budget records."""

import sqlite3

import pytest

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm.budget import BookLLMBudgetLedger


def test_corrupt_usage_record_is_rejected(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    ledger = BookLLMBudgetLedger(path)
    ledger.totals()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO calls (request_hash, provider_hash, status, total_tokens, "
            "prompt_tokens, completion_tokens) VALUES (?, ?, ?, ?, ?, ?)",
            ("hash", "model", "complete", -5, 10, 5),
        )
    with pytest.raises(LLMError, match="Invalid per-book LLM budget ledger entries"):
        ledger.totals()


def test_negative_estimated_cost_is_rejected(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    ledger = BookLLMBudgetLedger(path)
    ledger.totals()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO calls (request_hash, provider_hash, status, total_tokens, "
            "prompt_tokens, completion_tokens, estimated_usd) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("hash", "model", "complete", 15, 10, 5, "-0.01"),
        )
    with pytest.raises(LLMError, match="Invalid per-book LLM cost entries"):
        ledger.totals()
