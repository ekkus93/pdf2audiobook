"""Persistent LLM cost accounting must reject binary64 overflow before reporting."""

import pytest

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm.budget import BookLLMBudgetLedger


@pytest.mark.parametrize("cost", ["1e10000", "2e308"])
def test_finite_but_unrepresentable_cost_fails_closed(tmp_path, cost):
    ledger = BookLLMBudgetLedger(tmp_path / "book-budget.sqlite3")
    with ledger._connect() as connection:
        connection.execute(
            "INSERT INTO calls "
            "(request_hash, provider_hash, status, prompt_tokens, "
            "completion_tokens, total_tokens, estimated_usd) "
            "VALUES (?, ?, 'complete', ?, ?, ?, ?)",
            ("request", "provider", 1, 1, 2, cost),
        )

    actions = [
        ledger.totals,
        lambda: ledger.reserve(
            request_hash="new", provider_hash="provider",
            max_requests=None, max_tokens=None, max_usd=1.0,
        ),
        lambda: ledger.check_spend(max_tokens=None, max_usd=1.0),
    ]
    for action in actions:
        with pytest.raises(LLMError, match="Invalid per-book LLM cost entries") as error:
            action()
        assert cost not in str(error.value)
    with ledger._connect() as connection:
        # No additional paid request may be reserved after overflow.
        assert connection.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 1


def test_finite_cost_still_reports_normally(tmp_path):
    ledger = BookLLMBudgetLedger(tmp_path / "book-budget.sqlite3")
    with ledger._connect() as connection:
        connection.execute(
            "INSERT INTO calls "
            "(request_hash, provider_hash, status, prompt_tokens, "
            "completion_tokens, total_tokens, estimated_usd) "
            "VALUES (?, ?, 'complete', ?, ?, ?, ?)",
            ("request", "provider", 1, 1, 2, "1.25"),
        )
    assert ledger.totals()["estimated_cost_usd"] == 1.25
