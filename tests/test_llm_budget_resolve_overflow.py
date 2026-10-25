"""`budget resolve` cannot leave a ledger that `budget show` cannot read (R71)."""

import json

from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.llm.budget import BookLLMBudgetLedger

runner = CliRunner()


def _ledger_with_two_open_rows(workspace):
    ledger = BookLLMBudgetLedger(workspace / "reports" / "llm_budget.sqlite3")
    for name, bound in (("a", (1 << 62) + 5), ("b", 10)):
        call_id = ledger.reserve(
            request_hash=name,
            provider_hash="p",
            max_requests=None,
            max_tokens=None,
            max_usd=None,
            upper_bound_tokens=bound,
        )
        ledger.settle(call_id, usage=None, input_rate=None, output_rate=None)
    return ledger


def test_resolving_a_value_that_overflows_with_another_open_row_is_refused(tmp_path):
    ledger = _ledger_with_two_open_rows(tmp_path)
    before = ledger.rows()
    result = runner.invoke(
        app,
        [
            "budget",
            "resolve",
            "--output",
            str(tmp_path),
            "2",
            "--tokens",
            f"{1 << 62}:10",
            "--confirm",
            "--no-config",
        ],
    )
    assert result.exit_code == 2, result.stderr
    assert ledger.rows() == before
    shown = runner.invoke(app, ["budget", "show", "--output", str(tmp_path), "--json"])
    assert shown.exit_code == 0, shown.stderr
    assert json.loads(shown.stdout)["requests"][1]["status"] == "unknown"


def test_a_resolution_that_fits_is_still_accepted(tmp_path):
    ledger = _ledger_with_two_open_rows(tmp_path)
    result = runner.invoke(
        app,
        [
            "budget",
            "resolve",
            "--output",
            str(tmp_path),
            "2",
            "--tokens",
            "7:3",
            "--confirm",
            "--no-config",
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert ledger.rows()[1]["status"] == "complete"
