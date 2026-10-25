"""Budget rows distinguish provably unsent connections from ambiguous failures."""

import httpx
import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm import OpenAICompatibleProvider
from pdf2audiobook.llm.budget import BookLLMBudgetLedger
from pdf2audiobook.llm.cache import CachedLLMProvider


def run_failed_request(tmp_path, exception):
    def respond(request):
        raise exception("PRIVATE TRANSPORT DETAIL", request=request)

    ledger_path = tmp_path / "reports" / "llm_budget.sqlite3"
    with OpenAICompatibleProvider(
        provider="stub",
        model="local",
        base_url="http://127.0.0.1:11434/v1",
        allow_remote=False,
        transport=httpx.MockTransport(respond),
        max_retries=0,
        max_context_tokens=4096,
    ) as provider:
        worker = CachedLLMProvider(
            provider,
            cache_dir=tmp_path / "cache",
            identity="local-model",
            ledger_path=ledger_path,
            max_reported_tokens=3000,
        )
        with pytest.raises(LLMError):
            worker.complete_json(instructions="private instructions", document_text="private book")
    return BookLLMBudgetLedger(ledger_path)


def test_connect_failure_is_unbilled_and_does_not_block_budget(tmp_path):
    ledger = run_failed_request(tmp_path, httpx.ConnectError)
    assert ledger.rows()[0]["status"] == "unbilled"
    totals = ledger.totals()
    assert totals["unresolved_requests"] == 0
    assert totals["requests_started"] == 0
    ledger.reserve(
        request_hash="another-request",
        provider_hash="local-model",
        max_requests=1,
        max_tokens=3000,
        max_usd=None,
    )


def test_read_timeout_remains_unknown_and_blocks_token_budget(tmp_path):
    ledger = run_failed_request(tmp_path, httpx.ReadTimeout)
    assert ledger.rows()[0]["status"] == "unknown"
    assert ledger.totals()["unresolved_requests"] == 1
    assert ledger.totals()["reported_tokens"] > 0
    ledger.reserve(
        request_hash="another-request",
        provider_hash="local-model",
        max_requests=None,
        max_tokens=3000,
        max_usd=None,
        upper_bound_tokens=10,
    )


def test_budget_cli_resolve_and_show_are_content_free(tmp_path):
    workspace = tmp_path / "PRIVATE_WORKSPACE"
    ledger = BookLLMBudgetLedger(workspace / "reports" / "llm_budget.sqlite3")
    call_id = ledger.reserve(
        request_hash="content-hash",
        provider_hash="model-hash",
        max_requests=None,
        max_tokens=None,
        max_usd=None,
    )
    ledger.settle(call_id, usage=None, input_rate=None, output_rate=None)

    resolved = CliRunner().invoke(
        app,
        [
            "budget",
            "resolve",
            str(call_id),
            "--output",
            str(workspace),
            "--unbilled",
            "--confirm",
            "--no-config",
            "--json",
        ],
    )
    assert resolved.exit_code == 0, resolved.stderr
    shown = CliRunner().invoke(app, ["budget", "show", "--output", str(workspace), "--json"])
    assert shown.exit_code == 0, shown.stderr
    assert '"status": "unbilled"' in shown.stdout
    for private in ("PRIVATE_WORKSPACE", "private instructions", "private book", "content-hash"):
        assert private not in shown.stdout + shown.stderr + resolved.stdout + resolved.stderr


def test_budget_cli_resolves_unknown_usage_from_confirmed_counts(tmp_path):
    workspace = tmp_path / "workspace"
    ledger = BookLLMBudgetLedger(workspace / "reports" / "llm_budget.sqlite3")
    call_id = ledger.reserve(
        request_hash="request-hash",
        provider_hash="provider-hash",
        max_requests=None,
        max_tokens=None,
        max_usd=None,
    )
    ledger.settle(call_id, usage=None, input_rate=None, output_rate=None)
    result = CliRunner().invoke(
        app,
        [
            "budget",
            "resolve",
            str(call_id),
            "--output",
            str(workspace),
            "--tokens",
            "3:4",
            "--confirm",
            "--no-config",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stderr
    row = BookLLMBudgetLedger(workspace / "reports" / "llm_budget.sqlite3").rows()[0]
    assert row["status"] == "complete"
    assert (row["prompt_tokens"], row["completion_tokens"], row["total_tokens"]) == (3, 4, 7)
    BookLLMBudgetLedger(workspace / "reports" / "llm_budget.sqlite3").reserve(
        request_hash="next-request",
        provider_hash="provider-hash",
        max_requests=None,
        max_tokens=100,
        max_usd=None,
    )
