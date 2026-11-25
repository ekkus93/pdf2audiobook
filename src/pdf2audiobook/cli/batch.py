"""`batch`: convert every book in a folder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from pdf2audiobook.cli._core import (
    ClickExit,
    app,
    configure_effective_logging,
    emit,
    fail,
    fail_interrupted,
)
from pdf2audiobook.config import Settings, load_settings
from pdf2audiobook.errors import (
    AudioError,
    ConfigError,
    PartialConversionError,
)
from pdf2audiobook.logging import (
    set_output_mode,
)


@app.command(epilog="Example: pdf2audiobook batch ./books --no-llm --recursive --cover ./cover.png")
def batch(
    source_dir: Path = typer.Argument(..., help="Directory containing PDF books."),
    config: Path | None = typer.Option(None, "--config"),
    no_config: bool = typer.Option(False, "--no-config"),
    output: Path | None = typer.Option(None, "--output"),
    recursive: bool = typer.Option(
        False, "--recursive/--no-recursive", help="Search nested directories."
    ),
    resume: bool | None = typer.Option(None, "--resume/--no-resume"),
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
    clone_voice: bool | None = typer.Option(None, "--clone-voice/--no-clone-voice"),
    reference_audio: str | None = typer.Option(None, "--reference-audio", metavar="PATH"),
    reference_text_file: str | None = typer.Option(None, "--reference-text-file", metavar="PATH"),
    speed: float | None = typer.Option(None, "--speed", min=0.1, max=3.0),
    temperature: float | None = typer.Option(
        None,
        "--tts-temperature",
        min=0.05,
        max=1.5,
        help="Kitten 2 sampling temperature; lower stays closer to the text.",
    ),
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
        if resume is not None:
            overrides.setdefault("general", {})["resume"] = resume
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
        if temperature is not None:
            overrides.setdefault("tts", {}).setdefault("kitten", {})["temperature"] = temperature
        if bitrate is not None:
            overrides.setdefault("tts", {})["bitrate"] = bitrate
        if cover is not None:
            overrides.setdefault("audio", {})["cover_image"] = str(cover)
        from pdf2audiobook.cli.options import clone_overrides

        clone_overrides(
            overrides,
            clone_voice=clone_voice,
            reference_audio=reference_audio,
            reference_text_file=reference_text_file,
        )
        settings, origins = load_settings(config, no_config=no_config, overrides=overrides)
        configure_effective_logging(settings, origins)
        from pdf2audiobook.audio import read_cover_image

        read_cover_image(settings.audio.cover_image)
        from pdf2audiobook.pipeline import convert_book

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
                    ("temperature", temperature is not None),
                )
                if present
            )
            book_settings = _book_settings(settings, source, explicit, tts_model, voice, speed)
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
                results.append(_batch_failure(source, exc))
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


def _book_settings(
    settings: Settings,
    source: Path,
    explicit: frozenset[str],
    tts_model: str | None,
    voice: str | None,
    speed: float | None,
) -> Settings:
    from pdf2audiobook.pipeline import settings_for_book_tts, tts_selection
    from pdf2audiobook.tts.cloning import validate_clone_selection

    book_settings = settings_for_book_tts(settings, source.stem, explicit=explicit)
    validated = book_settings.model_dump()
    selected_provider, _selected_voice, _selected_speed = tts_selection(book_settings)
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
        book_settings._clone_explicit = settings._clone_explicit | (
            frozenset({"voice"}) if voice is not None else frozenset()
        )
        validate_clone_selection(book_settings)
    except (typer.Exit, ClickExit):
        raise
    except ConfigError:
        raise
    except Exception:
        raise ConfigError("Invalid per-book TTS settings for batch conversion") from None
    return book_settings


def _batch_failure(source: Path, exc: Exception) -> dict[str, Any]:
    from pdf2audiobook.errors import AudiobookError

    code = AudioError.exit_code if isinstance(exc, OSError) else getattr(exc, "exit_code", 1)
    result: dict[str, Any] = {"book": source.name, "ok": False, "error_code": code}
    if isinstance(exc, AudiobookError) and exc.error_reason:
        result["reason"] = exc.error_reason
    return result
