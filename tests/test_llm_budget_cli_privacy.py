"""Budget CLI failures never disclose workspace paths or ledger content."""

from typer.testing import CliRunner

from pdf2audiobook.cli import app


def test_budget_show_corrupt_ledger_error_is_content_free(tmp_path):
    workspace = tmp_path / "PRIVATE_BUDGET_WORKSPACE"
    ledger = workspace / "reports" / "llm_budget.sqlite3"
    ledger.parent.mkdir(parents=True)
    ledger.write_bytes(b"PRIVATE_LEDGER_BYTES")

    result = CliRunner().invoke(
        app,
        ["budget", "show", "--output", str(workspace), "--json"],
    )

    assert result.exit_code == 5
    for private in ("PRIVATE_BUDGET_WORKSPACE", "PRIVATE_LEDGER_BYTES", str(tmp_path)):
        assert private not in result.stdout + result.stderr
