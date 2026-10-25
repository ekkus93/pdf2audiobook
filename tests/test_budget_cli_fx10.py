"""Budget CLI behavior for retained legacy ledgers and row-specific resolve errors."""

import json
import sqlite3

from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.llm.budget import BookLLMBudgetLedger


def test_budget_show_reads_v2_ledger_without_migrating_it(tmp_path):
    workspace = tmp_path / "book"
    ledger_path = workspace / "reports" / "llm_budget.sqlite3"
    ledger_path.parent.mkdir(parents=True)
    with sqlite3.connect(ledger_path) as connection:
        connection.execute(
            "CREATE TABLE calls (id INTEGER PRIMARY KEY, request_hash TEXT NOT NULL, "
            "provider_hash TEXT NOT NULL, status TEXT NOT NULL, prompt_tokens INTEGER, "
            "completion_tokens INTEGER, total_tokens INTEGER, estimated_usd TEXT)"
        )
        connection.execute(
            "INSERT INTO calls VALUES (1, 'hash', 'provider', 'complete', 7, 3, 10, NULL)"
        )
        connection.execute("PRAGMA user_version=2")

    result = CliRunner().invoke(app, ["budget", "show", "--output", str(workspace), "--json"])

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["requests"][0]["total_tokens"] == 10
    with sqlite3.connect(ledger_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert "upper_bound_tokens" not in {
            row[1] for row in connection.execute("PRAGMA table_info(calls)")
        }


def test_budget_resolve_refuses_v2_ledger_without_migrating_it(tmp_path):
    workspace = tmp_path / "book"
    ledger_path = workspace / "reports" / "llm_budget.sqlite3"
    ledger_path.parent.mkdir(parents=True)
    with sqlite3.connect(ledger_path) as connection:
        connection.execute(
            "CREATE TABLE calls (id INTEGER PRIMARY KEY, request_hash TEXT NOT NULL, "
            "provider_hash TEXT NOT NULL, status TEXT NOT NULL, prompt_tokens INTEGER, "
            "completion_tokens INTEGER, total_tokens INTEGER, estimated_usd TEXT)"
        )
        connection.execute("PRAGMA user_version=2")

    result = _resolve(workspace, 1)

    assert result.exit_code == 2
    assert "Legacy budget ledger cannot be resolved; re-create the ledger" in result.stderr
    with sqlite3.connect(ledger_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2


def _resolve(workspace, request_id):
    return CliRunner().invoke(
        app,
        [
            "budget",
            "resolve",
            str(request_id),
            "--output",
            str(workspace),
            "--confirm",
            "--unbilled",
            "--no-config",
        ],
    )


def test_budget_resolve_missing_id_has_own_message_and_exit_2(tmp_path):
    workspace = tmp_path / "book"
    ledger = BookLLMBudgetLedger(workspace / "reports" / "llm_budget.sqlite3")
    ledger.totals()

    result = _resolve(workspace, 987)

    assert result.exit_code == 2
    assert "request ID does not exist" in result.stderr


def test_budget_resolve_complete_row_has_own_message_and_exit_2(tmp_path):
    workspace = tmp_path / "book"
    ledger = BookLLMBudgetLedger(workspace / "reports" / "llm_budget.sqlite3")
    request_id = ledger.reserve(
        request_hash="request",
        provider_hash="provider",
        max_requests=None,
        max_tokens=None,
        max_usd=None,
    )
    ledger.settle(
        request_id,
        usage={"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        input_rate=None,
        output_rate=None,
    )

    result = _resolve(workspace, request_id)

    assert result.exit_code == 2
    assert "request is already settled" in result.stderr
