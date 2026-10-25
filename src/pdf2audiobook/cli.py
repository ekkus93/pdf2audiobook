"""Typer CLI for inspection, analysis, conversion and configuration."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from importlib import import_module
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

try:
    ClickExit: type[BaseException] = getattr(import_module("click.exceptions"), "Exit")
except ImportError:
    ClickExit = typer.Exit

from pdf2audiobook import __version__
from pdf2audiobook.config import Settings, load_settings, settings_public
from pdf2audiobook.errors import (
    AudiobookError,
    AudioError,
    ConfigError,
    ExtractionError,
    LLMError,
    PartialConversionError,
    WorkspaceError,
)
from pdf2audiobook.logging import (
    begin_cli_command,
    configure_from_settings,
    configure_logging,
    log_event,
    set_output_mode,
    take_warning_codes,
    use_default_event_policy,
)

app = typer.Typer(
    no_args_is_help=True,
    help="Convert PDF books to chapter-based audiobooks.",
    epilog="Example: pdf2audiobook convert ./book.pdf --no-llm --cover ./cover.jpg",
    pretty_exceptions_enable=False,
)
config_app = typer.Typer(help="Inspect effective configuration.")
app.add_typer(config_app, name="config")
budget_app = typer.Typer(help="Inspect or resolve per-book LLM request accounting.")
app.add_typer(budget_app, name="budget")
console = Console(stderr=True)


def fail(exc: Exception, *, json_output: bool = False) -> None:
    """Report a stable exit code and optionally a machine-readable stderr diagnostic."""
    code = exc.exit_code if isinstance(exc, AudiobookError) else 1
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
                    "error": {"type": type(exc).__name__, "code": code, "message": message},
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


@app.callback()
def entry(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Show version."),
    verbose: bool = typer.Option(
        False, "--verbose", help="Emit privacy-safe debug events to stderr."
    ),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress non-error log events."),
) -> None:
    if verbose and quiet:
        raise typer.BadParameter("--verbose and --quiet cannot be combined")
    ctx.obj = {"verbose": verbose, "quiet": quiet}
    configure_logging(verbose=verbose, quiet=quiet)
    if not verbose:
        use_default_event_policy()
    begin_cli_command()
    log_event("command_started", level=logging.DEBUG, command=ctx.invoked_subcommand or "root")
    if version:
        typer.echo(__version__)
        raise typer.Exit()


@config_app.command("show", epilog="Example: pdf2audiobook config show --sources")
def show_config(
    config: Path | None = typer.Option(None, "--config"),
    no_config: bool = typer.Option(False, "--no-config"),
    sources: bool = typer.Option(False, "--sources"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    set_output_mode(json_output)
    try:
        settings, origin = load_settings(config, no_config=no_config)
        configure_effective_logging(settings, origin)
        payload = settings_public(settings)
        if origin.get("cache.directory", "built-in") != "built-in":
            payload["_unused_settings"] = ["cache.directory"]
        if sources:
            payload["_sources"] = origin
        emit(payload, json_output)
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


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
        except LLMError:
            raise ConfigError("Resolved values are invalid or exceed ledger limits") from None
        emit({"resolved": request_id, "status": stored_status}, json_output)
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


@app.command(epilog="Example: pdf2audiobook doctor --json")
def doctor(
    json_output: bool = typer.Option(False, "--json"),
    config: Path | None = typer.Option(None, "--config"),
    no_config: bool = typer.Option(False, "--no-config"),
) -> None:
    set_output_mode(json_output)
    try:
        settings, origins = load_settings(config, no_config=no_config)
        configure_effective_logging(settings, origins)
        try:
            from importlib import import_module

            import_module("kittenml")

            kitten_installed = True
        except ImportError:
            kitten_installed = False
        from pdf2audiobook.pdf import missing_ocr_languages, tesseract_languages

        languages = tesseract_languages()
        emit(
            {
                "version": __version__,
                "ffmpeg": bool(shutil.which("ffmpeg")),
                "tesseract": bool(shutil.which("tesseract")),
                "ocr_requested_languages": settings.pdf.ocr_language,
                "ocr_installed_languages": languages,
                "ocr_missing_languages": missing_ocr_languages(
                    settings.pdf.ocr_language, languages
                ),
                "kitten_installed": kitten_installed,
                "piper_installed": bool(shutil.which("piper")),
                "llm_provider": settings.llm.provider if settings.llm.enabled else "disabled",
            },
            json_output,
        )
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


@app.command(epilog="Example: pdf2audiobook inspect ./book.pdf --json")
def inspect(
    source: Path = typer.Argument(..., help="PDF/EPUB book or previously generated manifest.json"),
    pdf_password_env: str | None = typer.Option(
        None, "--pdf-password-env", help="Name of environment variable containing PDF password."
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    set_output_mode(json_output)
    try:
        if source.suffix.lower() == ".json":
            from pdf2audiobook.workspace import read_manifest

            manifest = read_manifest(source)
            from pdf2audiobook.document.structure import chapter_coverage_report

            payload = {
                "title": manifest.title,
                "chapters": [chapter.model_dump() for chapter in manifest.chapters],
                "warnings": manifest.warnings,
                "coverage": chapter_coverage_report(manifest),
            }
            from pdf2audiobook.jsonio import load_bounded_json

            conversion_status = load_bounded_json(
                source.parent / "reports" / "conversion_status.json",
                max_bytes=1024 * 1024,
                max_depth=16,
            )
            if isinstance(conversion_status, dict):
                payload["conversion_status"] = conversion_status
        else:
            from pdf2audiobook.pdf import inspect_pdf

            payload = inspect_pdf(source, password_env=pdf_password_env)
        emit(payload, json_output)
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


def _overrides(
    output: Path | None,
    ocr: str | None,
    no_llm: bool,
    llm_provider: str | None,
    llm_model: str | None,
    llm_url: str | None,
    allow_remote_content: bool | None,
    tts_model: str | None,
    voice: str | None,
    bitrate: str | None,
    resume: bool | None,
    allow_single_chapter: bool | None,
) -> dict[str, Any]:
    value: dict[str, Any] = {}
    if output is not None:
        value.setdefault("general", {})["output_dir"] = str(output)
    if resume is not None:
        value.setdefault("general", {})["resume"] = resume
    if ocr is not None:
        value.setdefault("pdf", {})["ocr"] = ocr
    if llm_provider is not None:
        value.setdefault("llm", {})["provider"] = llm_provider
    if no_llm:
        value.setdefault("llm", {})["enabled"] = False
    if allow_remote_content is not None:
        value.setdefault("llm", {})["allow_remote_content"] = allow_remote_content
    if llm_model is not None or llm_url is not None:
        provider = (llm_provider or "ollama").replace("-", "_")
        section = value.setdefault("llm", {}).setdefault(provider, {})
        if llm_model is not None:
            section["model"] = llm_model
        if llm_url is not None:
            section["base_url"] = llm_url
    if bitrate:
        value.setdefault("tts", {})["bitrate"] = bitrate
    if allow_single_chapter is not None:
        value.setdefault("chapters", {})["allow_single_chapter"] = allow_single_chapter
    return value


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
            None,
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
        if vision is not None:
            overrides.setdefault("llm", {})["vision"] = vision
        settings, origins = load_settings(config, no_config=no_config, overrides=overrides)
        configure_effective_logging(settings, origins)
        from pdf2audiobook.pipeline import analyze_book

        try:
            manifest_path = analyze_book(source, settings)
        except OSError:
            raise WorkspaceError("Cannot create the output workspace") from None
        emit({"manifest": str(manifest_path)}, json_output)
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


def parse_chapter_range(value: str) -> tuple[int, int]:
    """Parse inclusive, human-friendly 1-based A:B chapter selection."""
    if re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", value) is None:
        raise ConfigError("chapter range must be 1-based A:B, e.g. 2:5")
    first, last = (int(value_part) for value_part in value.split(":"))
    if last < first:
        raise ConfigError("chapter range end must not precede start")
    return first, last


@app.command(
    epilog="Example: pdf2audiobook convert ./book.pdf --no-llm --cover ./cover.jpg --allow-single-chapter"
)
def convert(
    source: Path = typer.Argument(...),
    config: Path | None = typer.Option(None, "--config"),
    no_config: bool = typer.Option(False, "--no-config"),
    output: Path | None = typer.Option(None, "--output"),
    ocr: str | None = typer.Option(None, "--ocr"),
    pdf_password_env: str | None = typer.Option(None, "--pdf-password-env"),
    llm_provider: str | None = typer.Option(None, "--llm-provider"),
    llm_model: str | None = typer.Option(None, "--llm-model"),
    llm_url: str | None = typer.Option(None, "--llm-url"),
    allow_remote_content: bool | None = typer.Option(
        None, "--allow-remote-content/--no-allow-remote-content"
    ),
    llm: bool | None = typer.Option(
        None, "--llm/--no-llm", help="Enable or disable LLM assistance."
    ),
    vision: bool | None = typer.Option(
        None, "--vision/--no-vision", help="Enable opt-in page-image review."
    ),
    tts_provider: str | None = typer.Option(None, "--tts-provider"),
    tts_model: str | None = typer.Option(None, "--tts-model"),
    voice: str | None = typer.Option(None, "--voice"),
    bitrate: str | None = typer.Option(None, "--bitrate"),
    chapter: int | None = typer.Option(None, "--chapter", min=1),
    chapter_range: str | None = typer.Option(
        None, "--chapter-range", help="Inclusive 1-based start:end (e.g. 2:5)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Analyze and plan chapter outputs without TTS synthesis."
    ),
    speed: float | None = typer.Option(None, "--speed", min=0.1, max=3.0),
    sample_rate: int | None = typer.Option(None, "--sample-rate", min=8000, max=96000),
    cover: Path | None = typer.Option(None, "--cover", help="JPEG or PNG chapter cover image."),
    accept_review: list[str] = typer.Option(
        [], "--accept-review", help="Acknowledge a review reason code for this book."
    ),
    resume: bool | None = typer.Option(None, "--resume/--no-resume"),
    force: bool = typer.Option(False, "--force", help="Regenerate selected chapter audio."),
    allow_single_chapter: bool | None = typer.Option(
        None, "--allow-single-chapter/--no-allow-single-chapter"
    ),
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
            tts_model,
            voice,
            bitrate,
            resume,
            allow_single_chapter,
        )
        if llm_model is not None or llm_url is not None:
            selected = provider.replace("-", "_")
            if selected != "ollama" and llm_provider is None:
                overrides["llm"][selected] = overrides["llm"].pop("ollama")
        effective_tts_provider = tts_provider or preliminary.tts.provider
        tts_values = overrides.setdefault("tts", {})
        if tts_provider is not None:
            tts_values["provider"] = tts_provider
        if tts_model is not None:
            key = "model_path" if effective_tts_provider == "piper" else "model"
            section = "piper" if effective_tts_provider == "piper" else "kitten"
            tts_values.setdefault(section, {})[key] = tts_model
        if voice is not None:
            tts_values.setdefault(effective_tts_provider, {})["voice"] = voice
        if pdf_password_env is not None:
            overrides.setdefault("pdf", {})["password_env"] = pdf_password_env
        if llm is True:
            overrides.setdefault("llm", {})["enabled"] = True
        if vision is not None:
            overrides.setdefault("llm", {})["vision"] = vision
        if speed is not None:
            overrides.setdefault("tts", {}).setdefault(effective_tts_provider, {})["speed"] = speed
        if sample_rate is not None:
            overrides.setdefault("tts", {})["sample_rate"] = sample_rate
        if cover is not None:
            overrides.setdefault("audio", {})["cover_image"] = str(cover)
        if chapter is not None and chapter_range is not None:
            raise ConfigError("--chapter and --chapter-range cannot be combined")
        selected_range = parse_chapter_range(chapter_range) if chapter_range else None
        from pdf2audiobook.review_reasons import BOOK_WIDE_REVIEW_REASON_CODES

        if "empty_chapter" in accept_review:
            raise ConfigError(
                "empty_chapter cannot be accepted globally; approve the chapter in the review UI"
            )
        if not set(accept_review) <= set(BOOK_WIDE_REVIEW_REASON_CODES):
            raise ConfigError(
                "Unknown --accept-review reason; choose from "
                + ", ".join(BOOK_WIDE_REVIEW_REASON_CODES)
            )
        settings, origins = load_settings(config, no_config=no_config, overrides=overrides)
        configure_effective_logging(settings, origins)
        from pdf2audiobook.audio import audio_output_path, read_cover_image
        from pdf2audiobook.pipeline import (
            analyze_book,
            convert_book,
            prepare_chapter_selection,
        )
        from pdf2audiobook.workspace import read_manifest

        read_cover_image(settings.audio.cover_image)
        if dry_run:
            manifest_path = analyze_book(source, settings)
            manifest = read_manifest(manifest_path)
            selection = prepare_chapter_selection(
                manifest_path,
                manifest,
                settings,
                chapter=chapter,
                chapter_range=selected_range,
                acknowledge=tuple(accept_review),
            )
            skipped_ids = {item.id for item in selection.skipped}
            chapters = [item for item in selection.chapters if item.id not in skipped_ids]
            output_files = [
                str(audio_output_path(manifest, item, manifest_path.parent)) for item in chapters
            ]
            emit(
                {
                    "dry_run": True,
                    "chapters": len(chapters),
                    "mp3_files": output_files,
                    "skipped_chapters": sorted(item.number for item in selection.skipped),
                    "would_acknowledge": selection.would_acknowledge,
                },
                json_output,
            )
        else:
            try:
                outputs = convert_book(
                    source,
                    settings,
                    chapter=chapter,
                    chapter_range=selected_range,
                    force=force,
                    accept_review=tuple(accept_review),
                )
            except OSError:
                raise WorkspaceError("Cannot create the output workspace") from None
            emit({"mp3_files": [str(path) for path in outputs]}, json_output)
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


@app.command(epilog="Example: pdf2audiobook batch ./books --no-llm --recursive --cover ./cover.png")
def batch(
    source_dir: Path = typer.Argument(..., help="Directory containing PDF books."),
    config: Path | None = typer.Option(None, "--config"),
    no_config: bool = typer.Option(False, "--no-config"),
    output: Path | None = typer.Option(None, "--output"),
    recursive: bool = typer.Option(
        False, "--recursive/--no-recursive", help="Search nested directories."
    ),
    llm: bool | None = typer.Option(
        None, "--llm/--no-llm", help="Enable or disable LLM assistance."
    ),
    allow_remote_content: bool | None = typer.Option(
        None, "--allow-remote-content/--no-allow-remote-content"
    ),
    vision: bool | None = typer.Option(None, "--vision/--no-vision"),
    allow_single_chapter: bool | None = typer.Option(
        None, "--allow-single-chapter/--no-allow-single-chapter"
    ),
    tts_provider: str | None = typer.Option(None, "--tts-provider"),
    tts_model: str | None = typer.Option(None, "--tts-model"),
    voice: str | None = typer.Option(None, "--voice"),
    speed: float | None = typer.Option(None, "--speed", min=0.1, max=3.0),
    sample_rate: int | None = typer.Option(None, "--sample-rate", min=8000, max=96000),
    bitrate: str | None = typer.Option(None, "--bitrate"),
    cover: Path | None = typer.Option(None, "--cover", help="JPEG or PNG chapter cover image."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Convert every PDF in a directory, applying a matching named TTS profile."""
    set_output_mode(json_output)
    try:
        preliminary, _ = load_settings(config, no_config=no_config)
        if not source_dir.is_dir():
            raise ConfigError("batch source must be a directory")
        files = source_dir.rglob("*") if recursive else source_dir.glob("*")
        sources = sorted(
            (path for path in files if path.is_file() and path.suffix.casefold() == ".pdf"),
            key=lambda path: str(path).casefold(),
        )
        if not sources:
            raise ConfigError("batch source directory contains no PDF files")
        overrides: dict[str, Any] = {}
        if output is not None:
            overrides.setdefault("general", {})["output_dir"] = str(output)
        if llm is not None:
            overrides.setdefault("llm", {})["enabled"] = llm
        if allow_remote_content is not None:
            overrides.setdefault("llm", {})["allow_remote_content"] = allow_remote_content
        if vision is not None:
            overrides.setdefault("llm", {})["vision"] = vision
        if allow_single_chapter is not None:
            overrides.setdefault("chapters", {})["allow_single_chapter"] = allow_single_chapter
        if tts_provider is not None:
            overrides.setdefault("tts", {})["provider"] = tts_provider
        if sample_rate is not None:
            overrides.setdefault("tts", {})["sample_rate"] = sample_rate
        if bitrate is not None:
            overrides.setdefault("tts", {})["bitrate"] = bitrate
        if cover is not None:
            overrides.setdefault("audio", {})["cover_image"] = str(cover)
        settings, origins = load_settings(config, no_config=no_config, overrides=overrides)
        configure_effective_logging(settings, origins)
        from pdf2audiobook.audio import read_cover_image

        read_cover_image(settings.audio.cover_image)
        from pdf2audiobook.pipeline import convert_book, settings_for_book_tts

        results: list[dict[str, Any]] = []
        failures = 0
        batch_jobs = []
        for source in sources:
            explicit = frozenset(
                key
                for key, present in (
                    ("tts_provider", tts_provider is not None),
                    ("tts_model", tts_model is not None),
                    ("voice", voice is not None),
                    ("speed", speed is not None),
                )
                if present
            )
            book_settings = settings_for_book_tts(settings, source.stem, explicit=explicit)
            validated = book_settings.model_dump()
            selected_provider = book_settings.tts.provider
            if tts_model is not None:
                section = "piper" if selected_provider == "piper" else "kitten"
                key = "model_path" if section == "piper" else "model"
                validated["tts"][section][key] = tts_model
            if voice is not None:
                validated["tts"][selected_provider]["voice"] = voice
            if speed is not None:
                validated["tts"][selected_provider]["speed"] = speed
            try:
                book_settings = Settings.model_validate(validated)
            except (typer.Exit, ClickExit):
                raise
            except Exception:
                raise ConfigError("Invalid per-book TTS settings for batch conversion") from None
            batch_jobs.append((source, book_settings))
        for source, book_settings in batch_jobs:
            configure_effective_logging(book_settings, origins)
            try:
                outputs = convert_book(source, book_settings)
            except KeyboardInterrupt:
                raise
            except (typer.Exit, ClickExit):
                raise
            except Exception as exc:
                failures += 1
                code = getattr(exc, "exit_code", 1)
                if isinstance(exc, OSError):
                    code = AudioError.exit_code
                results.append(
                    {
                        "book": source.name,
                        "ok": False,
                        "error_code": code,
                    }
                )
            else:
                results.append(
                    {"book": source.name, "ok": True, "mp3_files": [str(path) for path in outputs]}
                )
        emit({"books": results, "failed": failures}, json_output)
        if failures:
            raise PartialConversionError("One or more books failed")
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


@app.command(
    "pack-m4b",
    epilog="Example: pdf2audiobook pack-m4b ./audiobooks/BOOK/manifest.json --output ./book.m4b --cover ./cover.jpg",
)
def pack_m4b(
    manifest_path: Path = typer.Argument(..., help="Manifest from an analyzed/converted book."),
    output: Path = typer.Option(..., "--output", help="Destination .m4b file."),
    bitrate: str = typer.Option("96k", "--bitrate"),
    cover: Path | None = typer.Option(None, "--cover", help="Embed JPEG or PNG cover artwork."),
    config: Path | None = typer.Option(None, "--config"),
    no_config: bool = typer.Option(False, "--no-config"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Package completed chapter MP3s as a single M4B with chapter navigation."""
    set_output_mode(json_output)
    try:
        from pdf2audiobook.audio import audio_output_path, encode_m4b, read_cover_image
        from pdf2audiobook.document.structure import render_chapter_narration
        from pdf2audiobook.pipeline import prepare_chapter_selection, valid_mp3_sidecar
        from pdf2audiobook.workspace import read_manifest

        settings, origins = load_settings(
            config,
            no_config=no_config,
            overrides={"audio": {"cover_image": str(cover)}} if cover is not None else None,
        )
        configure_effective_logging(settings, origins)
        manifest = read_manifest(manifest_path)
        cover_image = read_cover_image(settings.audio.cover_image)
        selection = prepare_chapter_selection(manifest_path, manifest, settings)
        skipped_ids = {chapter.id for chapter in selection.skipped}
        chapter_files = []
        stale_chapters = []
        for chapter in selection.chapters:
            if chapter.id in skipped_ids:
                continue
            path = audio_output_path(manifest, chapter, manifest_path.parent)
            try:
                # convert reads this text back from disk with universal newlines.
                text = (
                    render_chapter_narration(manifest, chapter, settings.pdf.footnotes)
                    .replace("\r\n", "\n")
                    .replace("\r", "\n")
                )
            except ExtractionError:
                stale_chapters.append(chapter.number)
                continue
            metadata = valid_mp3_sidecar(path)
            if (
                metadata is None
                or metadata.get("chapter_id") != chapter.id
                or metadata.get("text_sha256") != hashlib.sha256(text.encode("utf-8")).hexdigest()
            ):
                stale_chapters.append(chapter.number)
                continue
            chapter_files.append((path, chapter.title))
        if stale_chapters:
            numbers = ", ".join(str(number) for number in stale_chapters)
            raise AudioError(
                f"Chapter audio is stale or missing for chapter(s): {numbers}; run convert"
            )
        try:
            result = encode_m4b(
                chapter_files,
                output,
                title=manifest.title,
                artist=manifest.author,
                bitrate=bitrate,
                cover_image=cover_image,
            )
        except OSError:
            raise WorkspaceError("Cannot create the output workspace") from None
        emit(
            {
                "m4b_file": str(result),
                "skipped_chapters": sorted(chapter.number for chapter in selection.skipped),
            },
            json_output,
        )
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


@app.command(epilog="Example: pdf2audiobook review ./audiobooks/BOOK/manifest.json")
def review(
    manifest_path: Path = typer.Argument(..., help="A generated manifest.json to review."),
    port: int = typer.Option(8765, "--port", min=0, max=65535),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Open a loopback-only browser editor for chapter titles and boundaries."""
    set_output_mode(json_output)
    try:
        from pdf2audiobook.review_ui import create_review_server

        if not manifest_path.is_file():
            raise WorkspaceError("Cannot create the output workspace")
        try:
            server = create_review_server(manifest_path, port=port)
        except OSError:
            raise ConfigError("Review server port is unavailable; choose another --port") from None
        console.print(f"Chapter review UI: http://127.0.0.1:{server.server_address[1]}/")
        console.print("Press Ctrl+C to stop the local review server.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            # Stopping the server is how the review session normally ends.
            console.print("Review server stopped.")
        finally:
            server.server_close()
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)
