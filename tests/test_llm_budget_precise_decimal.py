"""SQLite LLM budget gates use exact persisted decimals, not rounded display floats."""

import pytest

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm.budget import BookLLMBudgetLedger


@pytest.mark.parametrize(
    ("stored_cost", "postflight_reject", "reserve_reject"),
    [
        ("0.30000000000000001", True, True),
        ("0.29999999999999999", False, False),
        ("0.3", False, True),
    ],
)
def test_budget_gates_use_exact_cost(
    tmp_path,
    stored_cost,
    postflight_reject,
    reserve_reject,
):
    ledger = BookLLMBudgetLedger(tmp_path / "ledger.sqlite3")
    with ledger._connect() as connection:
        connection.execute(
            "INSERT INTO calls "
            "(request_hash, provider_hash, status, prompt_tokens, "
            "completion_tokens, total_tokens, estimated_usd) "
            "VALUES (?, ?, 'complete', ?, ?, ?, ?)",
            ("old", "provider", 1, 1, 2, stored_cost),
        )

    # Display-compatible totals round to binary64 without authorizing spend.
    totals = ledger.totals()
    assert totals["estimated_cost_usd"] == 0.3
    assert "_exact_cost_usd" not in totals

    if postflight_reject:
        with pytest.raises(LLMError, match="estimated cost budget"):
            ledger.check_spend(max_tokens=None, max_usd=0.3)
    else:
        ledger.check_spend(max_tokens=None, max_usd=0.3)

    def reserve():
        return ledger.reserve(
            request_hash="next",
            provider_hash="provider",
            max_requests=None,
            max_tokens=None,
            max_usd=0.3,
            upper_bound_usd="0",
        )

    if reserve_reject:
        with pytest.raises(LLMError, match="estimated cost budget"):
            reserve()
    else:
        assert isinstance(reserve(), int)
