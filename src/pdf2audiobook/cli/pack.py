"""`pack-m4b`: package converted chapters into one M4B audiobook."""

from __future__ import annotations

import hashlib
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
from pdf2audiobook.config import load_settings
from pdf2audiobook.errors import (
    AudioError,
    ExtractionError,
    WorkspaceError,
)
from pdf2audiobook.logging import (
    set_output_mode,
)
from pdf2audiobook.progress_display import (
    NullReporter,
    ProgressReporter,
    bind_workspace,
    format_elapsed,
)


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
    reporter: ProgressReporter = NullReporter()
    try:
        from pdf2audiobook.audio import audio_output_path, encode_m4b, read_cover_image
        from pdf2audiobook.chapter_artifacts import load_artifact_state, plan_chapter_artifacts
        from pdf2audiobook.document.structure import render_chapter_narration
        from pdf2audiobook.pipeline import prepare_chapter_selection, valid_mp3_sidecar
        from pdf2audiobook.workspace import read_manifest, workspace_lock

        settings, origins = load_settings(
            config,
            no_config=no_config,
            overrides={"audio": {"cover_image": str(cover)}} if cover is not None else None,
        )
        configure_effective_logging(settings, origins)
        with workspace_lock(manifest_path.parent):
            manifest = read_manifest(manifest_path)
            artifact_state = load_artifact_state(manifest_path.parent)
            artifact_plan = (
                plan_chapter_artifacts(manifest, manifest_path.parent, artifact_state["footnotes"])
                if artifact_state is not None
                else None
            )
            cover_image = read_cover_image(settings.audio.cover_image)
            selection = prepare_chapter_selection(
                manifest_path,
                manifest,
                settings,
                footnotes=artifact_state["footnotes"] if artifact_state is not None else None,
            )
            skipped_ids = {chapter.id for chapter in selection.skipped}
            chapter_files = []
            stale_chapters = []
            reporter = _progress_reporter(settings, json_output, "pack-m4b")
            bind_workspace(reporter, manifest_path.parent)
            started = time.monotonic()
            checking = reporter.stage(
                "Checking chapter audio",
                sum(1 for chapter in selection.chapters if chapter.id not in skipped_ids),
                "chapter",
            )
            for chapter in selection.chapters:
                if chapter.id in skipped_ids:
                    continue
                checking.advance()
                path = audio_output_path(manifest, chapter, manifest_path.parent)
                metadata = valid_mp3_sidecar(path)
                rendering_inputs = (
                    metadata.get("rendering_inputs") if metadata is not None else None
                )
                footnotes = (
                    rendering_inputs.get("footnotes")
                    if isinstance(rendering_inputs, dict)
                    else None
                )
                if (
                    metadata is None
                    or metadata.get("chapter_id") != chapter.id
                    or not isinstance(footnotes, str)
                    or (artifact_state is not None and footnotes != artifact_state["footnotes"])
                ):
                    stale_chapters.append(chapter.number)
                    continue
                try:
                    # convert reads this text back from disk with universal newlines.
                    name = f"{chapter.number:03d}.txt"
                    if artifact_plan is not None:
                        if name in artifact_plan.writes:
                            stale_chapters.append(chapter.number)
                            continue
                        text = (manifest_path.parent / "chapters" / name).read_text(
                            encoding="utf-8"
                        )
                    else:
                        text = (manifest_path.parent / "chapters" / name).read_text(
                            encoding="utf-8"
                        )
                        if text != render_chapter_narration(manifest, chapter, footnotes):
                            stale_chapters.append(chapter.number)
                            continue
                    text = text.replace("\r\n", "\n").replace("\r", "\n")
                except (ExtractionError, OSError, UnicodeError):
                    stale_chapters.append(chapter.number)
                    continue
                if (
                    metadata is None
                    or metadata.get("text_sha256")
                    != hashlib.sha256(text.encode("utf-8")).hexdigest()
                ):
                    stale_chapters.append(chapter.number)
                    continue
                chapter_files.append((path, chapter.title))
            checking.close()
            if stale_chapters:
                numbers = ", ".join(str(number) for number in stale_chapters)
                raise AudioError(
                    f"Chapter audio is stale or missing for chapter(s): {numbers}; run convert"
                )
            # A single ffmpeg run cannot report fractional progress: elapsed time only.
            encoding = reporter.stage("Encoding M4B", None, "file")
            try:
                result = encode_m4b(
                    chapter_files,
                    output,
                    title=manifest.title,
                    artist=manifest.author,
                    bitrate=bitrate,
                    cover_image=cover_image,
                )
                encoding.advance()
            except OSError:
                raise WorkspaceError("Cannot create the output workspace") from None
            finally:
                encoding.close()
            emit(
                {
                    "m4b_file": str(result),
                    "skipped_chapters": sorted(chapter.number for chapter in selection.skipped),
                },
                json_output,
            )
            reporter.summary(
                f"Packaged {len(chapter_files)} chapter(s) in "
                f"{format_elapsed(time.monotonic() - started)}"
            )
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)
    finally:
        reporter.close()
