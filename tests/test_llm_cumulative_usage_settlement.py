"""Cumulative provider usage overflow must remain repairable in the budget ledger."""

import json

import httpx
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.llm import OpenAICompatibleProvider
from pdf2audiobook.llm.budget import BookLLMBudgetLedger
from pdf2audiobook.llm.cache import CachedLLMProvider


def test_cumulative_usage_overflow_is_unknown_and_resolvable(tmp_path):
    replies = iter(
        [
            httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": '{"ok":true}'}}],
                    "usage": {
                        "prompt_tokens": 1 << 62,
                        "completion_tokens": 0,
                        "total_tokens": 1 << 62,
                    },
                },
            )
            for _ in range(2)
        ]
    )
    ledger_path = tmp_path / "reports" / "llm_budget.sqlite3"
    with OpenAICompatibleProvider(
        provider="stub",
        model="local",
        base_url="http://127.0.0.1:11434/v1",
        allow_remote=False,
        transport=httpx.MockTransport(lambda _request: next(replies)),
        max_context_tokens=4096,
    ) as provider:
        worker = CachedLLMProvider(
            provider,
            cache_dir=tmp_path / "cache",
            identity="local-provider",
            ledger_path=ledger_path,
        )
        worker.complete_json(instructions="task", document_text="first")
        worker.complete_json(instructions="task", document_text="second")

    runner = CliRunner()
    shown = runner.invoke(app, ["budget", "show", "--output", str(tmp_path), "--json"])
    assert shown.exit_code == 0, shown.stderr
    assert json.loads(shown.stdout)["requests"][1]["status"] == "unknown"

    resolved = runner.invoke(
        app,
        [
            "budget",
            "resolve",
            "2",
            "--output",
            str(tmp_path),
            "--tokens",
            "10:2",
            "--confirm",
            "--no-config",
        ],
    )
    assert resolved.exit_code == 0, resolved.stderr
    assert BookLLMBudgetLedger(ledger_path).rows()[1]["status"] == "complete"
