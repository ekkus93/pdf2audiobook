"""`verify-audio` and the saved audio report (`audio-report show`, `dismiss`)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import typer

from pdf2audiobook.cli._core import (
    ClickExit,
    _progress_reporter,
    app,
    audio_report_app,
    configure_effective_logging,
    console,
    emit,
    fail,
    fail_interrupted,
    stop_with_message,
)
from pdf2audiobook.config import Settings, load_settings
from pdf2audiobook.errors import (
    ConfigError,
)
from pdf2audiobook.logging import (
    set_output_mode,
)
from pdf2audiobook.progress_display import (
    NullReporter,
    ProgressReporter,
    bind_workspace,
    format_elapsed,
    use_reporter,
)


@app.command(
    "verify-audio",
    epilog="Example: pdf2audiobook verify-audio ./audiobooks/BOOK/manifest.json --chapter 3",
)
def verify_audio(
    manifest_path: Path = typer.Argument(..., help="Manifest of a converted book."),
    chapter: list[int] = typer.Option([], "--chapter", min=1, help="Chapter to check; repeatable."),
    chapter_range: str | None = typer.Option(None, "--chapter-range", help="START:END, inclusive."),
    models: list[str] = typer.Option(
        [],
        "--models",
        help="whisper, wav2vec2, vosk or all (default); repeatable or comma-separated.",
    ),
    device: str = typer.Option(
        "auto", "--device", help="auto, cpu or cuda for Whisper and Wav2Vec2."
    ),
    keep_transcripts: bool = typer.Option(
        False, "--keep-transcripts", help="Keep full transcripts in the report, not just excerpts."
    ),
    details: bool = typer.Option(False, "--details", help="Show expected and heard words."),
    config: Path | None = typer.Option(None, "--config"),
    no_config: bool = typer.Option(False, "--no-config"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Listen to chapter MP3s with local speech recognizers and flag possible mismatches."""
    set_output_mode(json_output)
    reporter: ProgressReporter = NullReporter()
    try:
        from pdf2audiobook.verification.models import resolve_names
        from pdf2audiobook.verification.report import report_text
        from pdf2audiobook.verification.run import select_chapters, verify_book
        from pdf2audiobook.workspace import read_manifest, workspace_lock

        if device not in {"auto", "cpu", "cuda"}:
            raise ConfigError("--device must be auto, cpu or cuda")
        names = resolve_names([part for value in models for part in value.split(",") if part])
        settings, origins = load_settings(config, no_config=no_config)
        configure_effective_logging(settings, origins)
        with workspace_lock(manifest_path.parent):
            manifest = read_manifest(manifest_path)
            chosen = select_chapters(manifest, chapter, chapter_range)
            reporter = _progress_reporter(settings, json_output, "verify-audio")
            bind_workspace(reporter, manifest_path.parent)
            with use_reporter(reporter):
                report = verify_book(
                    manifest_path.parent, manifest, settings, chosen,
                    models=names, device=device, keep_transcripts=keep_transcripts,
                    reporter=reporter,
                )  # fmt: skip
        reporter.close()
        if json_output:
            emit(report, json_output)
        else:
            typer.echo(report_text(report, numbers={c.number for c in chosen}, details=details))
    except KeyboardInterrupt:
        reporter.close()
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit) as exc:
        stop_with_message(exc, json_output=json_output)
    except Exception as exc:
        reporter.close()
        fail(exc, json_output=json_output)


@audio_report_app.command(
    "show", epilog="Example: pdf2audiobook audio-report show ./audiobooks/BOOK/manifest.json --json"
)
def audio_report_show(
    manifest_path: Path = typer.Argument(..., help="Manifest of a converted book."),
    config: Path | None = typer.Option(None, "--config"),
    no_config: bool = typer.Option(False, "--no-config"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show the saved verification report and which results are stale; loads no model."""
    set_output_mode(json_output)
    try:
        from pdf2audiobook.verification.report import report_text
        from pdf2audiobook.verification.run import saved_report, stale_chapters
        from pdf2audiobook.workspace import read_manifest

        settings, origins = load_settings(config, no_config=no_config)
        configure_effective_logging(settings, origins)
        workspace = manifest_path.parent
        manifest = read_manifest(manifest_path)
        report = saved_report(workspace)
        stale = sorted(stale_chapters(workspace, manifest, settings, report)) if report else []
        payload = {"schema_version": 1, "report": report, "stale": stale}
        if json_output:
            emit(payload, json_output)
        elif report is None:
            typer.echo("This book has not been verified yet.")
        else:
            typer.echo(report_text(report))
            if stale:
                typer.echo("Out of date (verify again): chapter(s) " + ", ".join(map(str, stale)))
    except (typer.Exit, ClickExit) as exc:
        stop_with_message(exc, json_output=json_output)
    except Exception as exc:
        fail(exc, json_output=json_output)


@audio_report_app.command(
    "dismiss",
    epilog="Example: pdf2audiobook audio-report dismiss ./audiobooks/BOOK/manifest.json "
    "--chapter 3 --flag 0",
)
def audio_report_dismiss(
    manifest_path: Path = typer.Argument(..., help="Manifest of a converted book."),
    chapter: int = typer.Option(..., "--chapter", min=1),
    flag: int = typer.Option(..., "--flag", min=0, help="The flag's position in the chapter."),
    undo: bool = typer.Option(False, "--undo", help="Mark the flag not reviewed again."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Mark a flagged passage reviewed after listening; changes no audio or text."""
    set_output_mode(json_output)
    try:
        from pdf2audiobook.verification.run import mark_reviewed
        from pdf2audiobook.workspace import workspace_lock

        with workspace_lock(manifest_path.parent):
            mark_reviewed(manifest_path.parent, chapter, flag, reviewed=not undo)
        payload = {"chapter": chapter, "flag": flag, "reviewed": not undo}
        if json_output:
            emit(payload, json_output)
        else:
            typer.echo("Marked reviewed." if not undo else "Marked not reviewed.")
    except (typer.Exit, ClickExit) as exc:
        stop_with_message(exc, json_output=json_output)
    except Exception as exc:
        fail(exc, json_output=json_output)


def _verify_after_convert(
    outputs: list[Path], settings: Settings, json_output: bool
) -> tuple[dict[str, Any], list[str], str] | None:
    """`convert --verify-audio`: verify the chapters this conversion produced (spec §3, §12).

    The conversion has already succeeded; a mismatch adds a warning, never a failure.
    """
    from pdf2audiobook.audio import audio_output_path
    from pdf2audiobook.verification.report import report_text
    from pdf2audiobook.verification.run import verify_book
    from pdf2audiobook.workspace import read_manifest, workspace_lock

    if not outputs:
        return None
    workspace = outputs[0].parent.parent
    produced = {path.resolve() for path in outputs}
    reporter = _progress_reporter(settings, json_output, "verify-audio")
    try:
        with workspace_lock(workspace):
            manifest = read_manifest(workspace / "manifest.json")
            chosen = [
                chapter
                for chapter in manifest.chapters
                if audio_output_path(manifest, chapter, workspace).resolve() in produced
            ]
            bind_workspace(reporter, workspace)
            with use_reporter(reporter):
                report = verify_book(workspace, manifest, settings, chosen, reporter=reporter)
    finally:
        reporter.close()
    numbers = {chapter.number for chapter in chosen}
    chapters = [c for c in report["chapters"] if c["number"] in numbers]
    summary = {
        "report": "reports/audio_verification.json",
        "chapters": [
            {
                "number": c["number"],
                "status": c["status"],
                "reason": c["reason"],
                "partial": c["partial"],
                "flags": sum(1 for f in c["flags"] if f["confirmed"]),
            }
            for c in chapters
        ],
    }
    warnings = list(report["warnings"])
    if any(c["status"] == "possible_mismatch" for c in chapters):
        warnings.append("audio_possible_mismatch")
    return summary, warnings, report_text(report, numbers=numbers)


def _manifest_chapters(manifest_path: Path) -> list[Any]:
    from pdf2audiobook.workspace import read_manifest

    return list(read_manifest(manifest_path).chapters)


@app.command(
    "resynthesize",
    epilog="Example: pdf2audiobook resynthesize ./audiobooks/BOOK/manifest.json --chapter 3",
)
def resynthesize(
    manifest_path: Path = typer.Argument(..., help="Manifest of a converted book."),
    chapter: list[int] = typer.Option(
        [], "--chapter", min=1, help="Chapter to speak again; repeatable."
    ),
    voice: str | None = typer.Option(None, "--voice", help="Voice for this retry."),
    tts_provider: str | None = typer.Option(None, "--tts-provider"),
    tts_model: str | None = typer.Option(None, "--tts-model"),
    clone_voice: bool | None = typer.Option(None, "--clone-voice/--no-clone-voice"),
    reference_audio: str | None = typer.Option(None, "--reference-audio", metavar="PATH"),
    reference_text_file: str | None = typer.Option(None, "--reference-text-file", metavar="PATH"),
    speed: float | None = typer.Option(None, "--speed", min=0.1, max=3.0),
    cover: Path | None = typer.Option(
        None, "--cover", help="Cover art; by default the art already in the chapter MP3 is kept."
    ),
    verify_audio: bool | None = typer.Option(
        None,
        "--verify-audio/--no-verify-audio",
        help="Check the new audio afterwards (default: when the chapter was checked before).",
    ),
    config: Path | None = typer.Option(None, "--config"),
    no_config: bool = typer.Option(False, "--no-config"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Speak chosen chapters again from the analyzed book, keeping the previous audio."""
    set_output_mode(json_output)
    reporter: ProgressReporter = NullReporter()
    try:
        from pdf2audiobook.audio import read_cover_image
        from pdf2audiobook.pipeline import resynthesize_chapters
        from pdf2audiobook.verification.run import previous_chapters

        if not chapter:
            raise ConfigError("Name at least one --chapter to synthesize again")
        preliminary, _ = load_settings(config, no_config=no_config)
        provider = tts_provider or preliminary.tts.provider
        overrides: dict[str, Any] = {}
        if voice is not None or speed is not None:
            overrides = {
                "tts": {
                    provider: {
                        k: v for k, v in (("voice", voice), ("speed", speed)) if v is not None
                    }
                }
            }
        if tts_provider is not None:
            overrides.setdefault("tts", {})["provider"] = tts_provider
        if tts_model is not None:
            section, key = ("piper", "model_path") if provider == "piper" else ("kitten", "model")
            overrides.setdefault("tts", {}).setdefault(section, {})[key] = tts_model
        from pdf2audiobook.cli.options import clone_overrides
        from pdf2audiobook.tts.cloning import validate_clone_selection

        clone_overrides(
            overrides,
            clone_voice=clone_voice,
            reference_audio=reference_audio,
            reference_text_file=reference_text_file,
        )
        settings, origins = load_settings(config, no_config=no_config, overrides=overrides or None)
        from pdf2audiobook.tts.selection import settings_for_book_tts
        from pdf2audiobook.workspace import read_manifest

        if settings.tts.profiles:
            source_stem = Path(read_manifest(manifest_path).source_path).stem
            settings = settings_for_book_tts(
                settings,
                source_stem,
                explicit=frozenset(
                    key
                    for key, present in (
                        ("tts_provider", tts_provider is not None),
                        ("tts_model", tts_model is not None),
                        ("voice", voice is not None),
                        ("speed", speed is not None),
                    )
                    if present
                ),
            )
        validate_clone_selection(settings)
        configure_effective_logging(settings, origins)
        cover_image = read_cover_image(cover) if cover is not None else None
        workspace = manifest_path.parent
        checked_before = set(previous_chapters(workspace)) & set(chapter)
        reporter = _progress_reporter(settings, json_output, "resynthesize")
        started = time.monotonic()
        try:
            with use_reporter(reporter):
                outputs = resynthesize_chapters(
                    manifest_path,
                    settings,
                    list(chapter),
                    cover_image=cover_image,
                    progress=reporter,
                )
        finally:
            reporter.close()
        payload: dict[str, Any] = {"mp3_files": [str(path) for path in outputs]}
        if voice is not None and any(
            c.voice_id for c in _manifest_chapters(manifest_path) if c.number in set(chapter)
        ):
            payload["warnings"] = ["chapter_voice_overrides_option"]
        verification = None
        if verify_audio or (verify_audio is None and checked_before):
            verification = _verify_after_convert(outputs, settings, json_output)
        if verification is not None:
            payload["audio_verification"], warnings, text = verification
            payload["warnings"] = [*payload.get("warnings", []), *warnings]
        emit(payload, json_output)
        reporter.summary(
            f"Synthesized {len(outputs)} chapter(s) again in {format_elapsed(time.monotonic() - started)}; "
            "the previous audio is in audio/.backup/"
        )
        if verification is not None and not json_output:
            console.print(verification[2])
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit) as exc:
        stop_with_message(exc, json_output=json_output)
    except Exception as exc:
        fail(exc, json_output=json_output)
