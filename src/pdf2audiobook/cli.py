"""Typer CLI for inspection, analysis, conversion and configuration."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from pdf2audiobook import __version__
from pdf2audiobook.config import load_settings, settings_public
from pdf2audiobook.errors import AudiobookError, ConfigError
from pdf2audiobook.logging import configure_logging, log_event

app = typer.Typer(no_args_is_help=True, help="Convert PDF books to chapter-based audiobooks.")
config_app = typer.Typer(help="Inspect effective configuration.")
app.add_typer(config_app, name="config")
console = Console(stderr=True)


def fail(exc: Exception, *, json_output: bool = False) -> None:
    """Report a stable exit code and optionally a machine-readable stderr diagnostic."""
    code = exc.exit_code if isinstance(exc, AudiobookError) else 1
    # Never log exception text, file paths, credentials, or PDF contents.
    log_event("command_failed", error_code=code)
    if json_output:
        # Diagnostics belong on stderr; stdout is reserved for successful JSON payloads.
        typer.echo(
            json.dumps(
                {
                    "ok": False,
                    "error": {"type": type(exc).__name__, "code": code, "message": str(exc)},
                },
                ensure_ascii=False,
            ),
            err=True,
        )
    else:
        console.print(f"[red]Error:[/red] {exc}")
    raise typer.Exit(code=code) from exc


def emit(payload: dict[str, Any], json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        console.print_json(data=payload)


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
    configure_logging(verbose=verbose, quiet=quiet)
    log_event("command_started", command=ctx.invoked_subcommand or "root")
    if version:
        typer.echo(__version__)
        raise typer.Exit()


@config_app.command("show")
def show_config(
    config: Path | None = typer.Option(None, "--config"),
    no_config: bool = typer.Option(False, "--no-config"),
    sources: bool = typer.Option(False, "--sources"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    try:
        settings, origin = load_settings(config, no_config=no_config)
        payload = settings_public(settings)
        if sources:
            payload["_sources"] = origin
        emit(payload, json_output)
    except (AudiobookError, OSError, ValueError) as exc:
        fail(exc, json_output=json_output)


@app.command()
def doctor(
    json_output: bool = typer.Option(False, "--json"),
    config: Path | None = typer.Option(None, "--config"),
    no_config: bool = typer.Option(False, "--no-config"),
) -> None:
    try:
        settings, _ = load_settings(config, no_config=no_config)
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
    except (AudiobookError, OSError, ValueError) as exc:
        fail(exc, json_output=json_output)


@app.command()
def inspect(
    source: Path = typer.Argument(..., help="PDF/EPUB book or previously generated manifest.json"),
    pdf_password_env: str | None = typer.Option(
        None, "--pdf-password-env", help="Name of environment variable containing PDF password."
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
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
        else:
            from pdf2audiobook.pdf import inspect_pdf

            payload = inspect_pdf(source, password_env=pdf_password_env)
        emit(payload, json_output)
    except (AudiobookError, OSError, ValueError) as exc:
        fail(exc, json_output=json_output)


def _overrides(
    output: Path | None,
    ocr: str | None,
    no_llm: bool,
    llm_provider: str | None,
    llm_model: str | None,
    llm_url: str | None,
    allow_remote_content: bool,
    tts_model: str | None,
    voice: str | None,
    bitrate: str | None,
    resume: bool | None,
    allow_single_chapter: bool,
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
    if allow_remote_content:
        value.setdefault("llm", {})["allow_remote_content"] = True
    if llm_model is not None or llm_url is not None:
        provider = (llm_provider or "ollama").replace("-", "_")
        section = value.setdefault("llm", {}).setdefault(provider, {})
        if llm_model is not None:
            section["model"] = llm_model
        if llm_url is not None:
            section["base_url"] = llm_url
    if tts_model:
        value.setdefault("tts", {}).setdefault("kitten", {})["model"] = tts_model
    if voice:
        value.setdefault("tts", {}).setdefault("kitten", {})["voice"] = voice
    if bitrate:
        value.setdefault("tts", {})["bitrate"] = bitrate
    if allow_single_chapter:
        value.setdefault("chapters", {})["allow_single_chapter"] = True
    return value


@app.command()
def analyze(
    source: Path = typer.Argument(...),
    config: Path | None = typer.Option(None, "--config"),
    no_config: bool = typer.Option(False, "--no-config"),
    output: Path | None = typer.Option(None, "--output"),
    ocr: str | None = typer.Option(None, "--ocr"),
    pdf_password_env: str | None = typer.Option(None, "--pdf-password-env"),
    no_llm: bool = typer.Option(False, "--no-llm"),
    llm_provider: str | None = typer.Option(None, "--llm-provider"),
    llm_model: str | None = typer.Option(None, "--llm-model"),
    llm_url: str | None = typer.Option(None, "--llm-url"),
    allow_remote_content: bool = typer.Option(False, "--allow-remote-content"),
    vision: bool = typer.Option(False, "--vision", help="Enable opt-in page-image review."),
    allow_single_chapter: bool = typer.Option(False, "--allow-single-chapter"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    try:
        preliminary, _ = load_settings(config, no_config=no_config)
        provider = llm_provider or preliminary.llm.provider
        overrides = _overrides(
            output,
            ocr,
            no_llm,
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
        if vision:
            overrides.setdefault("llm", {})["vision"] = True
        settings, _ = load_settings(config, no_config=no_config, overrides=overrides)
        from pdf2audiobook.pipeline import analyze_book

        emit({"manifest": str(analyze_book(source, settings))}, json_output)
    except (AudiobookError, OSError, ValueError) as exc:
        fail(exc, json_output=json_output)


def parse_chapter_range(value: str) -> tuple[int, int]:
    """Parse inclusive, human-friendly 1-based A:B chapter selection."""
    if re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", value) is None:
        raise ConfigError("chapter range must be 1-based A:B, e.g. 2:5")
    first, last = (int(value_part) for value_part in value.split(":"))
    if last < first:
        raise ConfigError("chapter range end must not precede start")
    return first, last


@app.command()
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
    no_llm: bool = typer.Option(False, "--no-llm"),
    allow_remote_content: bool = typer.Option(False, "--allow-remote-content"),
    vision: bool = typer.Option(False, "--vision", help="Enable opt-in page-image review."),
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
    resume: bool | None = typer.Option(None, "--resume/--no-resume"),
    force: bool = typer.Option(False, "--force", help="Regenerate selected chapter audio."),
    allow_single_chapter: bool = typer.Option(False, "--allow-single-chapter"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    try:
        preliminary, _ = load_settings(config, no_config=no_config)
        provider = llm_provider or preliminary.llm.provider
        overrides = _overrides(
            output,
            ocr,
            no_llm,
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
        if tts_provider is not None:
            overrides.setdefault("tts", {})["provider"] = tts_provider
        if tts_provider == "piper":
            piper = overrides.setdefault("tts", {}).setdefault("piper", {})
            if tts_model is not None:
                piper["model_path"] = tts_model
            if voice is not None:
                piper["voice"] = voice
        if pdf_password_env is not None:
            overrides.setdefault("pdf", {})["password_env"] = pdf_password_env
        if vision:
            overrides.setdefault("llm", {})["vision"] = True
        if speed is not None:
            overrides.setdefault("tts", {}).setdefault("kitten", {})["speed"] = speed
            if tts_provider == "piper":
                overrides.setdefault("tts", {}).setdefault("piper", {})["speed"] = speed
        if sample_rate is not None:
            overrides.setdefault("tts", {})["sample_rate"] = sample_rate
        if chapter is not None and chapter_range is not None:
            raise ConfigError("--chapter and --chapter-range cannot be combined")
        selected_range = parse_chapter_range(chapter_range) if chapter_range else None
        settings, _ = load_settings(config, no_config=no_config, overrides=overrides)
        from pdf2audiobook.audio import audio_output_path
        from pdf2audiobook.pipeline import analyze_book, convert_book, select_chapters
        from pdf2audiobook.workspace import read_manifest

        if dry_run:
            manifest_path = analyze_book(source, settings)
            manifest = read_manifest(manifest_path)
            chapters = select_chapters(
                manifest, settings, chapter=chapter, chapter_range=selected_range
            )
            output_files = [
                str(audio_output_path(manifest, item, manifest_path.parent)) for item in chapters
            ]
            emit(
                {"dry_run": True, "chapters": len(chapters), "mp3_files": output_files}, json_output
            )
        else:
            outputs = convert_book(
                source,
                settings,
                chapter=chapter,
                chapter_range=selected_range,
                force=force,
            )
            emit({"mp3_files": [str(path) for path in outputs]}, json_output)
    except (AudiobookError, OSError, ValueError) as exc:
        fail(exc, json_output=json_output)


@app.command()
def batch(
    source_dir: Path = typer.Argument(..., help="Directory containing PDF books."),
    config: Path | None = typer.Option(None, "--config"),
    no_config: bool = typer.Option(False, "--no-config"),
    output: Path | None = typer.Option(None, "--output"),
    recursive: bool = typer.Option(False, "--recursive", help="Search nested directories."),
    no_llm: bool = typer.Option(False, "--no-llm"),
    allow_remote_content: bool = typer.Option(False, "--allow-remote-content"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Convert every PDF in a directory, applying a matching named TTS profile."""
    try:
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
        if no_llm:
            overrides.setdefault("llm", {})["enabled"] = False
        if allow_remote_content:
            overrides.setdefault("llm", {})["allow_remote_content"] = True
        settings, _ = load_settings(config, no_config=no_config, overrides=overrides)
        from pdf2audiobook.pipeline import convert_book, settings_for_book_tts

        results: list[dict[str, Any]] = []
        failures = 0
        for source in sources:
            book_settings = settings_for_book_tts(settings, source.stem)
            try:
                outputs = convert_book(source, book_settings)
            except (AudiobookError, OSError, ValueError) as exc:
                failures += 1
                results.append(
                    {
                        "book": source.name,
                        "ok": False,
                        "error_code": getattr(exc, "exit_code", 1),
                    }
                )
            else:
                results.append(
                    {"book": source.name, "ok": True, "mp3_files": [str(path) for path in outputs]}
                )
        emit({"books": results, "failed": failures}, json_output)
        if failures:
            raise typer.Exit(code=7)
    except (AudiobookError, OSError, ValueError) as exc:
        fail(exc, json_output=json_output)


@app.command("pack-m4b")
def pack_m4b(
    manifest_path: Path = typer.Argument(..., help="Manifest from an analyzed/converted book."),
    output: Path = typer.Option(..., "--output", help="Destination .m4b file."),
    bitrate: str = typer.Option("96k", "--bitrate"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Package completed chapter MP3s as a single M4B with chapter navigation."""
    try:
        from pdf2audiobook.audio import audio_output_path, encode_m4b
        from pdf2audiobook.workspace import read_manifest

        manifest = read_manifest(manifest_path)
        chapter_files = [
            (audio_output_path(manifest, chapter, manifest_path.parent), chapter.title)
            for chapter in manifest.chapters
        ]
        if any(not path.is_file() for path, _ in chapter_files):
            raise ConfigError("all chapter MP3 files must exist before M4B packaging")
        result = encode_m4b(
            chapter_files,
            output,
            title=manifest.title,
            artist=manifest.author,
            bitrate=bitrate,
        )
        emit({"m4b_file": str(result)}, json_output)
    except (AudiobookError, OSError, ValueError) as exc:
        fail(exc, json_output=json_output)


@app.command()
def review(
    manifest_path: Path = typer.Argument(..., help="A generated manifest.json to review."),
    port: int = typer.Option(8765, "--port", min=0, max=65535),
) -> None:
    """Open a loopback-only browser editor for chapter titles and boundaries."""
    try:
        from pdf2audiobook.review_ui import create_review_server

        server = create_review_server(manifest_path, port=port)
        console.print(f"Chapter review UI: http://127.0.0.1:{server.server_address[1]}/")
        console.print("Press Ctrl+C to stop the local review server.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    except (AudiobookError, OSError, ValueError) as exc:
        fail(exc)
