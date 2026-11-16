"""`asr list` and `asr fetch`: the optional speech recognizers."""

from __future__ import annotations

import typer

from pdf2audiobook.cli._core import ClickExit, asr_app, console, emit, fail, fail_interrupted
from pdf2audiobook.errors import (
    ConfigError,
)
from pdf2audiobook.logging import (
    set_output_mode,
)


@asr_app.command("list", epilog="Example: pdf2audiobook asr list --json")
def asr_list(json_output: bool = typer.Option(False, "--json")) -> None:
    """Show whether each ASR model is installed and downloaded, without loading it."""
    set_output_mode(json_output)
    try:
        from pdf2audiobook.verification.models import list_payload, list_text

        payload = list_payload()
        if json_output:
            emit(payload, json_output)
        else:
            typer.echo(list_text(payload))
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


@asr_app.command("fetch", epilog="Example: pdf2audiobook asr fetch whisper vosk")
def asr_fetch(
    models: list[str] = typer.Argument(None, help="whisper, wav2vec2, vosk or all (default)."),
    yes: bool = typer.Option(False, "--yes", help="Download without asking first."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Download pinned ASR model weights, after saying what, from where and how much."""
    set_output_mode(json_output)
    try:
        from pdf2audiobook.verification import models as asr

        names = asr.resolve_names(list(models or []))
        plan = asr.fetch_plan(names)
        if any(files for _, files in plan) and not yes:
            if json_output:
                raise ConfigError("Pass --yes to download models with --json")
            console.print(asr.plan_text([(n, f) for n, f in plan if f]))
            if not typer.confirm("Download these files?", default=False, err=True):
                raise typer.Exit(1)
        fetched = []
        for name, files in plan:
            if files:
                done = asr.fetch(
                    name,
                    on_file=None
                    if json_output
                    else lambda f: console.print(f"Downloading {f.name}..."),
                )
                fetched.append({"model": name, "files": [f.name for f in done]})
        payload = {**asr.list_payload(), "fetched": fetched}
        if json_output:
            emit(payload, json_output)
        else:
            typer.echo(asr.list_text(payload))
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)
