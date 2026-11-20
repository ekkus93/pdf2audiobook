"""Shared pieces of the command line: the Typer apps, output and error helpers, root options and `main`."""

from __future__ import annotations

import json
import logging
import signal
from importlib import import_module
from typing import Any

import typer
from rich.console import Console

from pdf2audiobook import __version__
from pdf2audiobook.config import Settings
from pdf2audiobook.errors import (
    AudiobookError,
)
from pdf2audiobook.logging import (
    begin_cli_command,
    configure_from_settings,
    configure_logging,
    log_event,
    take_warning_codes,
    use_default_event_policy,
)
from pdf2audiobook.progress_display import (
    ProgressReporter,
    StatusReporter,
    make_reporter,
)

try:
    ClickExit: type[BaseException] = getattr(import_module("click.exceptions"), "Exit")
except ImportError:
    ClickExit = typer.Exit


app = typer.Typer(
    no_args_is_help=True,
    help="Convert PDF books to chapter-based audiobooks.",
    epilog="Example: pdf2audiobook convert ./book.pdf --no-llm --cover ./cover.jpg",
    pretty_exceptions_enable=False,
)


config_app = typer.Typer(
    help="Create, validate or inspect configuration.",
    epilog="Example: pdf2audiobook config init",
)


app.add_typer(config_app, name="config")


budget_app = typer.Typer(
    help="Inspect or resolve per-book LLM request accounting.",
    epilog="Example: pdf2audiobook budget show --output ./audiobooks/BOOK",
)


app.add_typer(budget_app, name="budget")


edits_app = typer.Typer(
    help="Review pending edits that analysis proposed (LLM cleanup, equation readings).",
    epilog="Example: pdf2audiobook edits list ./audiobooks/BOOK/manifest.json",
)


app.add_typer(edits_app, name="edits")


asr_app = typer.Typer(
    help="List or fetch the optional speech recognizers that audio verification uses.",
    epilog="Example: pdf2audiobook asr list",
)


app.add_typer(asr_app, name="asr")

audio_report_app = typer.Typer(
    help="Read a book's saved audio verification report and mark flags reviewed.",
    no_args_is_help=True,
)


app.add_typer(audio_report_app, name="audio-report")


console = Console(stderr=True)


CONVERSION_STATUS_MAX_BYTES = 1024 * 1024


def fail(exc: Exception, *, json_output: bool = False) -> None:
    """Report a stable exit code and optionally a machine-readable stderr diagnostic."""
    code = exc.exit_code if isinstance(exc, AudiobookError) else 1
    reason = exc.error_reason if isinstance(exc, AudiobookError) else None
    if isinstance(exc, AudiobookError):
        message = str(exc)
    elif isinstance(exc, OSError):
        message = "A filesystem operation failed"
    elif isinstance(exc, ValueError):
        message = "Invalid input value"
    else:
        message = "Unexpected internal error"
    # Never log exception text, file paths, credentials, or PDF contents.
    log_event("command_failed", level=logging.ERROR, error_code=code)
    if json_output:
        warnings = take_warning_codes()
        # Diagnostics belong on stderr; stdout is reserved for successful JSON payloads.
        typer.echo(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "type": type(exc).__name__,
                        "code": code,
                        "message": message,
                        **({"reason": reason} if reason is not None else {}),
                    },
                    "warnings": warnings,
                },
                ensure_ascii=False,
            ),
            err=True,
        )
    else:
        console.print(f"[red]Error:[/red] {message}")
    raise typer.Exit(code=code) from exc


def stop_with_message(exc: BaseException, *, json_output: bool = False) -> None:
    """Pass a deliberate exit code through, with a fixed message saying what happened.

    A command that stops with a non-zero exit code says so, in the same JSON or human form as
    `fail`, and exits with the same code. The message holds the code only, never a path.
    """
    code = int(getattr(exc, "exit_code", 0) or 0)
    if code == 0:
        raise exc
    message = f"The command stopped with exit code {code}."
    log_event("command_stopped", level=logging.WARNING, error_code=code)
    if json_output:
        warnings = take_warning_codes()
        typer.echo(
            json.dumps(
                {
                    "ok": False,
                    "error": {"type": "Stopped", "code": code, "message": message},
                    "warnings": warnings,
                },
                ensure_ascii=False,
            ),
            err=True,
        )
    else:
        console.print(f"[red]Error:[/red] {message}")
    raise typer.Exit(code=code) from exc


def fail_interrupted(*, json_output: bool = False) -> None:
    """Exit cleanly and privately when the operator interrupts a command."""
    message = "Interrupted"
    log_event("command_failed", level=logging.ERROR, error_code=130)
    if json_output:
        warnings = take_warning_codes()
        typer.echo(
            json.dumps(
                {
                    "ok": False,
                    "error": {"type": "Interrupted", "code": 130, "message": message},
                    "warnings": warnings,
                }
            ),
            err=True,
        )
    else:
        console.print(f"[red]Error:[/red] {message}")
    raise typer.Exit(code=130)


def _progress_reporter(settings: Settings, json_output: bool, command: str) -> ProgressReporter:
    """Resolve --progress/--no-progress, --heartbeat, ``general.*``, --json and --quiet.

    The result always keeps ``reports/run_status.json``; it draws bars and prints
    heartbeats only where the options allow.
    """
    forced = _ROOT_OPTIONS.get("progress")
    mode = "always" if forced is True else "never" if forced is False else settings.general.progress
    inner = make_reporter(mode, json_output=json_output, quiet=bool(_ROOT_OPTIONS.get("quiet")))
    beat = _ROOT_OPTIONS.get("heartbeat")
    heartbeat = float(beat) if beat is not None else settings.general.heartbeat_seconds
    return StatusReporter(
        inner,
        command=command,
        heartbeat_seconds=0.0 if _ROOT_OPTIONS.get("quiet") else heartbeat,
    )


def emit(payload: dict[str, Any], json_output: bool) -> None:
    if json_output:
        result = dict(payload)
        warning_codes = take_warning_codes()
        existing_warnings = result.get("warnings")
        if isinstance(existing_warnings, list):
            result["warnings"] = [*existing_warnings, *warning_codes]
        else:
            result["warnings"] = warning_codes
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        console.print_json(data=payload)


def configure_effective_logging(settings: Settings, origins: dict[str, str]) -> None:
    configure_from_settings(
        settings.general.log_level,
        cache_directory_configured=origins.get("cache.directory", "built-in") != "built-in",
        explicit=origins.get("general.log_level", "built-in") != "built-in",
    )


_ROOT_OPTIONS: dict[str, Any] = {}


def _show_version(value: bool) -> None:
    """Print the version and stop, even when no command follows."""
    if value:
        typer.echo(__version__)
        raise typer.Exit()


def _initialize(value: bool) -> None:
    """An eager alias allows --init without a subcommand, like --version."""
    if value:
        from pdf2audiobook.cli.configuration import init_config

        init_config(config=None, json_output=False)
        raise typer.Exit()


@app.callback()
def entry(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", help="Show version.", is_eager=True, callback=_show_version
    ),
    init: bool = typer.Option(
        False,
        "--init",
        help="Create the default configuration file without replacing an existing file.",
        is_eager=True,
        callback=_initialize,
    ),
    verbose: bool = typer.Option(
        False, "--verbose", help="Emit privacy-safe debug events to stderr."
    ),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress non-error log events."),
    heartbeat: float | None = typer.Option(
        None,
        "--heartbeat",
        min=0,
        max=3600,
        help="Print one status line to stderr every N seconds (0 turns it off).",
    ),
    progress: bool | None = typer.Option(
        None,
        "--progress/--no-progress",
        help="Force progress bars with time estimates on or off (default: when stderr is a terminal).",
    ),
) -> None:
    if verbose and quiet:
        raise typer.BadParameter("--verbose and --quiet cannot be combined")
    ctx.obj = {"verbose": verbose, "quiet": quiet, "progress": progress, "heartbeat": heartbeat}
    _ROOT_OPTIONS.clear()
    _ROOT_OPTIONS.update(ctx.obj)
    configure_logging(verbose=verbose, quiet=quiet)
    if not verbose:
        use_default_event_policy()
    begin_cli_command()
    from pdf2audiobook.tts.private import cleanup_private_jobs

    cleanup_private_jobs()
    log_event("command_started", level=logging.DEBUG, command=ctx.invoked_subcommand or "root")


def _stop_on_sigterm(_signum: int, _frame: object) -> None:
    # Ctrl+C's path already stops at a safe point, records the run as stopped,
    # releases the workspace lock and exits 130; SIGTERM takes the same path.
    raise KeyboardInterrupt


def main() -> None:
    """Console entry point: SIGTERM stops a run the same way Ctrl+C does."""
    signal.signal(signal.SIGTERM, _stop_on_sigterm)
    app()
