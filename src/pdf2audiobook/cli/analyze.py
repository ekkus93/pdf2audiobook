"""`analyze`: find chapters and cleanup decisions for a book."""

from __future__ import annotations

import time
from pathlib import Path

import typer

from pdf2audiobook.cli._core import (
    ClickExit,
    _progress_reporter,
    app,
    configure_effective_logging,
    emit,
    fail,
    fail_interrupted,
)
from pdf2audiobook.cli.options import _overrides
from pdf2audiobook.config import load_settings
from pdf2audiobook.errors import (
    WorkspaceError,
)
from pdf2audiobook.logging import (
    set_output_mode,
)
from pdf2audiobook.progress_display import (
    format_elapsed,
    use_reporter,
)


@app.command(epilog="Example: pdf2audiobook analyze ./book.pdf --no-llm --output ./audiobooks")
def analyze(
    source: Path = typer.Argument(...),
    config: Path | None = typer.Option(None, "--config"),
    no_config: bool = typer.Option(False, "--no-config"),
    output: Path | None = typer.Option(None, "--output"),
    ocr: str | None = typer.Option(None, "--ocr"),
    pdf_password_env: str | None = typer.Option(None, "--pdf-password-env"),
    llm_provider: str | None = typer.Option(None, "--llm-provider"),
    llm_model: str | None = typer.Option(None, "--llm-model"),
    llm_url: str | None = typer.Option(None, "--llm-url"),
    llm_context_tokens: int | None = typer.Option(
        None,
        "--llm-context-tokens",
        min=512,
        help="Context window to budget for, e.g. 262144 for a 256k model.",
    ),
    llm_output_tokens: int | None = typer.Option(
        None,
        "--llm-output-tokens",
        min=1,
        help="Cap on tokens the model may write per request, e.g. 32768 for reasoning models.",
    ),
    process_citations: bool | None = typer.Option(
        None,
        "--process-citations/--no-process-citations",
        help="Skip numeric citations such as [13] in the audio.",
    ),
    process_equations: bool | None = typer.Option(
        None,
        "--process-equations/--no-process-equations",
        help="Have the LLM propose spoken readings of equations (pending your approval).",
    ),
    allow_remote_content: bool | None = typer.Option(
        None, "--allow-remote-content/--no-allow-remote-content"
    ),
    llm: bool | None = typer.Option(
        None, "--llm/--no-llm", help="Enable or disable LLM assistance."
    ),
    vision: bool | None = typer.Option(
        None, "--vision/--no-vision", help="Enable opt-in page-image review."
    ),
    allow_single_chapter: bool | None = typer.Option(
        None, "--allow-single-chapter/--no-allow-single-chapter"
    ),
    resume: bool | None = typer.Option(None, "--resume/--no-resume"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    set_output_mode(json_output)
    try:
        preliminary, _ = load_settings(config, no_config=no_config)
        provider = llm_provider or preliminary.llm.provider
        overrides = _overrides(
            output,
            ocr,
            llm is False,
            llm_provider,
            llm_model,
            llm_url,
            allow_remote_content,
            None,
            None,
            None,
            resume,
            allow_single_chapter,
        )
        if llm_model is not None or llm_url is not None:
            selected = provider.replace("-", "_")
            if selected != "ollama" and llm_provider is None:
                overrides["llm"][selected] = overrides["llm"].pop("ollama")
        if pdf_password_env is not None:
            overrides.setdefault("pdf", {})["password_env"] = pdf_password_env
        if llm is True:
            overrides.setdefault("llm", {})["enabled"] = True
        if llm_context_tokens is not None:
            overrides.setdefault("llm", {})["max_context_tokens"] = llm_context_tokens
        if llm_output_tokens is not None:
            overrides.setdefault("llm", {})["max_output_tokens"] = llm_output_tokens
        if process_citations is not None:
            overrides.setdefault("reading", {})["process_citations"] = process_citations
        if process_equations is not None:
            overrides.setdefault("reading", {})["process_equations"] = process_equations
        if vision is not None:
            overrides.setdefault("llm", {})["vision"] = vision
        settings, origins = load_settings(config, no_config=no_config, overrides=overrides)
        configure_effective_logging(settings, origins)
        from pdf2audiobook.pipeline import analyze_book

        reporter = _progress_reporter(settings, json_output, "analyze")
        started = time.monotonic()
        try:
            with use_reporter(reporter):
                manifest_path = analyze_book(source, settings)
        except OSError:
            raise WorkspaceError("Cannot create the output workspace") from None
        finally:
            reporter.close()
        emit({"manifest": str(manifest_path)}, json_output)
        reporter.summary(f"Analysis finished in {format_elapsed(time.monotonic() - started)}")
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)
