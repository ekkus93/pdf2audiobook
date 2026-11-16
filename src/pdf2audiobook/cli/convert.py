"""`convert`: synthesize chapter audio, with its dry run and verification hook."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import typer

from pdf2audiobook.cli._core import (
    ClickExit,
    _progress_reporter,
    app,
    configure_effective_logging,
    console,
    emit,
    fail,
    fail_interrupted,
)
from pdf2audiobook.cli.options import _check_accept_review, _convert_overrides, parse_chapter_range
from pdf2audiobook.cli.verify import _verify_after_convert
from pdf2audiobook.config import Settings, load_settings
from pdf2audiobook.errors import (
    ConfigError,
    WorkspaceError,
)
from pdf2audiobook.logging import (
    set_output_mode,
)
from pdf2audiobook.progress_display import (
    format_elapsed,
    use_reporter,
)


def _dry_run_convert(
    source: Path,
    settings: Settings,
    reporter: Any,
    *,
    chapter: int | None,
    chapter_range: tuple[int, int] | None,
    accept_review: tuple[str, ...],
    json_output: bool,
) -> None:
    """Analyze the book and report the MP3 files a conversion would write."""
    from pdf2audiobook.audio import audio_output_path
    from pdf2audiobook.pipeline import analyze_book, prepare_chapter_selection
    from pdf2audiobook.workspace import read_manifest, workspace_lock

    try:
        with use_reporter(reporter):
            manifest_path = analyze_book(source, settings)
    finally:
        reporter.close()
    with workspace_lock(manifest_path.parent):
        manifest = read_manifest(manifest_path)
        selection = prepare_chapter_selection(
            manifest_path,
            manifest,
            settings,
            chapter=chapter,
            chapter_range=chapter_range,
            acknowledge=accept_review,
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


def _run_convert(
    source: Path,
    settings: Settings,
    reporter: Any,
    *,
    chapter: int | None,
    chapter_range: tuple[int, int] | None,
    force: bool,
    accept_review: tuple[str, ...],
    json_output: bool,
    started: float,
    verify_audio: bool = False,
) -> None:
    """Convert the book and report its MP3 files and elapsed time."""
    from pdf2audiobook.pipeline import convert_book

    try:
        with use_reporter(reporter):
            outputs = convert_book(
                source,
                settings,
                chapter=chapter,
                chapter_range=chapter_range,
                force=force,
                accept_review=accept_review,
            )
    except OSError:
        raise WorkspaceError("Cannot create the output workspace") from None
    finally:
        reporter.close()
    payload: dict[str, Any] = {"mp3_files": [str(path) for path in outputs]}
    verification = _verify_after_convert(outputs, settings, json_output) if verify_audio else None
    if verification is not None:
        payload["audio_verification"], warnings, text = verification
        payload["warnings"] = warnings
    emit(payload, json_output)
    reporter.summary(
        f"Finished {len(outputs)} chapter(s) in {format_elapsed(time.monotonic() - started)}"
    )
    if verification is not None and not json_output:
        console.print(verification[2])


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
    verify_audio: bool = typer.Option(
        False,
        "--verify-audio",
        help="Then check the converted chapters with the local speech recognizers (asr extras).",
    ),
    allow_single_chapter: bool | None = typer.Option(
        None, "--allow-single-chapter/--no-allow-single-chapter"
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    set_output_mode(json_output)
    try:
        preliminary, _ = load_settings(config, no_config=no_config)
        overrides = _convert_overrides(
            preliminary,
            output=output,
            ocr=ocr,
            pdf_password_env=pdf_password_env,
            llm_provider=llm_provider,
            llm_model=llm_model,
            llm_url=llm_url,
            llm_context_tokens=llm_context_tokens,
            llm_output_tokens=llm_output_tokens,
            process_citations=process_citations,
            process_equations=process_equations,
            allow_remote_content=allow_remote_content,
            llm=llm,
            vision=vision,
            tts_provider=tts_provider,
            tts_model=tts_model,
            voice=voice,
            bitrate=bitrate,
            speed=speed,
            sample_rate=sample_rate,
            cover=cover,
            resume=resume,
            allow_single_chapter=allow_single_chapter,
        )
        if chapter is not None and chapter_range is not None:
            raise ConfigError("--chapter and --chapter-range cannot be combined")
        if dry_run and verify_audio:
            raise ConfigError(
                "--verify-audio needs real audio; it can't be combined with --dry-run"
            )
        selected_range = parse_chapter_range(chapter_range) if chapter_range else None
        _check_accept_review(accept_review)
        settings, origins = load_settings(config, no_config=no_config, overrides=overrides)
        configure_effective_logging(settings, origins)
        from pdf2audiobook.audio import read_cover_image

        read_cover_image(settings.audio.cover_image)
        reporter = _progress_reporter(settings, json_output, "convert")
        started = time.monotonic()
        if dry_run:
            _dry_run_convert(
                source,
                settings,
                reporter,
                chapter=chapter,
                chapter_range=selected_range,
                accept_review=tuple(accept_review),
                json_output=json_output,
            )
        else:
            _run_convert(
                source,
                settings,
                reporter,
                chapter=chapter,
                chapter_range=selected_range,
                force=force,
                accept_review=tuple(accept_review),
                json_output=json_output,
                started=started,
                verify_audio=verify_audio,
            )
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)
