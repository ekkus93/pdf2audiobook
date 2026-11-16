"""`budget show` and `budget resolve`: the LLM spending ledger."""

from __future__ import annotations

from pathlib import Path

import typer

from pdf2audiobook.cli._core import (
    ClickExit,
    budget_app,
    configure_effective_logging,
    emit,
    fail,
    fail_interrupted,
)
from pdf2audiobook.config import load_settings
from pdf2audiobook.errors import (
    ConfigError,
    LLMError,
)
from pdf2audiobook.logging import (
    set_output_mode,
)


@budget_app.command("show", epilog="Example: pdf2audiobook budget show --output ./audiobooks/BOOK")
def budget_show(
    output: Path = typer.Option(..., "--output", help="Book workspace directory."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show content-free request statuses and token/cost totals."""
    set_output_mode(json_output)
    try:
        from pdf2audiobook.llm.budget import BookLLMBudgetLedger

        ledger_path = output / "reports" / "llm_budget.sqlite3"
        if not ledger_path.is_file():
            raise ConfigError("Per-book LLM budget ledger does not exist")
        ledger = BookLLMBudgetLedger(ledger_path)
        emit(
            {"requests": ledger.rows(readonly=True), "totals": ledger.totals(readonly=True)},
            json_output,
        )
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


@budget_app.command(
    "resolve",
    epilog="Example: pdf2audiobook budget resolve --output ./audiobooks/BOOK --confirm --unbilled 12",
)
def budget_resolve(
    output: Path = typer.Option(..., "--output", help="Book workspace directory."),
    request_id: int = typer.Argument(..., min=1),
    tokens: str | None = typer.Option(None, "--tokens", help="Verified PROMPT:COMPLETION counts."),
    unbilled: bool = typer.Option(False, "--unbilled", help="Confirm the request was never sent."),
    confirm: bool = typer.Option(False, "--confirm", help="Confirm this ledger change."),
    config: Path | None = typer.Option(None, "--config"),
    no_config: bool = typer.Option(False, "--no-config"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Resolve an unknown request after checking provider billing evidence."""
    set_output_mode(json_output)
    try:
        from pdf2audiobook.llm.budget import BookLLMBudgetLedger

        if not confirm or (unbilled == (tokens is not None)):
            raise ConfigError("Choose exactly one resolution and pass --confirm")
        usage = None
        if tokens is not None:
            parts = tokens.split(":")
            if len(parts) != 2 or any(not part.isdecimal() for part in parts):
                raise ConfigError("--tokens must use PROMPT:COMPLETION nonnegative integers")
            prompt, completion = (int(part) for part in parts)
            if prompt > (1 << 63) - 1 or completion > (1 << 63) - 1:
                raise ConfigError("Token counts exceed the supported range")
            usage = {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": prompt + completion,
            }
        settings, origins = load_settings(config, no_config=no_config)
        configure_effective_logging(settings, origins)
        ledger_path = output / "reports" / "llm_budget.sqlite3"
        if not ledger_path.is_file():
            raise ConfigError("Per-book LLM budget ledger does not exist")
        ledger = BookLLMBudgetLedger(ledger_path)
        try:
            stored_status = ledger.resolve_unknown(
                request_id,
                usage=usage,
                input_rate=settings.llm.input_cost_usd_per_million_tokens,
                output_rate=settings.llm.output_cost_usd_per_million_tokens,
                unbilled=unbilled,
            )
        except LLMError as exc:
            # These two fixed row-state messages are safe and actionable. Other
            # ledger failures remain deliberately content-free.
            if str(exc) in {
                "Budget request ID does not exist",
                "Budget request is already settled",
                "Legacy budget ledger cannot be resolved; re-create the ledger",
            }:
                raise ConfigError(str(exc)) from None
            raise ConfigError("Resolved values are invalid or exceed ledger limits") from None
        emit({"resolved": request_id, "status": stored_status}, json_output)
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)
