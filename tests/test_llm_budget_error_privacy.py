"""SQLite ledger failures must not expose private paths or corrupt values."""

import sqlite3
from pathlib import Path

import pytest

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm.budget import BookLLMBudgetLedger

PRIVATE = "SYNTHETIC_PRIVATE_LEDGER_PATH_529"


@pytest.mark.parametrize("method", ["totals", "reserve", "settle", "check_spend"])
def test_ledger_sqlite_failures_hide_raw_diagnostics(
    monkeypatch, tmp_path: Path, method: str
) -> None:
    def fail_connection(*_args, **_kwargs):
        raise sqlite3.OperationalError(f"private ledger path: {PRIVATE}")

    monkeypatch.setattr(sqlite3, "connect", fail_connection)
    ledger = BookLLMBudgetLedger(tmp_path / "ledger.sqlite")
    kwargs = {
        "totals": {},
        "reserve": {
            "request_hash": "synthetic", "provider_hash": "test",
            "max_requests": None, "max_tokens": None, "max_usd": None,
        },
        "settle": {
            "call_id": 1, "usage": None,
            "input_rate": None, "output_rate": None,
        },
        "check_spend": {"max_tokens": None, "max_usd": None},
    }[method]
    with pytest.raises(LLMError) as raised:
        getattr(ledger, method)(**kwargs)
    assert PRIVATE not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


def test_invalid_persisted_cost_does_not_escape_in_exception_chain(tmp_path: Path):
    path = tmp_path / "ledger.sqlite"
    ledger = BookLLMBudgetLedger(path)
    ledger.totals()  # Initialize the schema.
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO calls (request_hash, provider_hash, status, "
            "prompt_tokens, completion_tokens, total_tokens, estimated_usd) "
            "VALUES (?, ?, 'complete', 1, 0, 1, ?)",
            ("synthetic", "test", PRIVATE),
        )
    with pytest.raises(LLMError, match="Invalid per-book LLM budget ledger") as raised:
        ledger.totals()
    assert PRIVATE not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True
