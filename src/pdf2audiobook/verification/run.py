"""Verify a book's chapter audio with the local ASR models and write the report (spec §3, §5).

One model at a time: each loads once, listens to every selected chapter, and is released
before the next (spec §13). A model that isn't ready, or fails on a chapter, abstains. If the
run is interrupted, chapters that some models finished keep a partial result and the rest are
`cancelled`; the report is still written, and the interruption is passed on. Nothing here
logs book text or transcripts.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pdf2audiobook.config import Settings
from pdf2audiobook.errors import AudioError, ConfigError
from pdf2audiobook.jsonio import load_bounded_json
from pdf2audiobook.models import BookManifest, Chapter
from pdf2audiobook.progress_display import NullReporter, ProgressReporter
from pdf2audiobook.verification import compare
from pdf2audiobook.verification.backends import backend as make_backend
from pdf2audiobook.verification.backends import decode
from pdf2audiobook.verification.contracts import (
    MODEL_NAMES,
    AsrBackend,
    Cancelled,
    ChapterResult,
    Difference,
    ModelName,
    ModelRun,
    Readiness,
    Word,
)
from pdf2audiobook.verification.reference import Reference, Unavailable, chapter_reference
from pdf2audiobook.verification.report import (
    chapter_json,
    report_json,
    retains_transcripts,
    without_transcripts,
)
from pdf2audiobook.workspace import digest_file, write_json

REPORT = Path("reports") / "audio_verification.json"
REPORT_MAX_BYTES = 64 * 1024 * 1024
# Whisper on a CPU peaked at about 7 GB (spec §13).
WHISPER_CPU_RAM_BYTES = 8 * 1024**3

BackendFactory = Callable[[ModelName], AsrBackend]


@dataclass
class _Chapter:
    chapter: Chapter
    reference: Reference
    tokens: list[compare.Token]
    wav: Path | None = None
    duration: float | None = None
    runs: dict[ModelName, ModelRun] = field(default_factory=dict)
    transcripts: dict[ModelName, tuple[Word, ...]] = field(default_factory=dict)


def select_chapters(
    manifest: BookManifest, numbers: Sequence[int] = (), chapter_range: str | None = None
) -> list[Chapter]:
    """The chapters to verify: those named, a START:END range, or all of them."""
    chosen = set(numbers)
    if chapter_range:
        try:
            first, last = (int(part) for part in chapter_range.split(":"))
        except ValueError:
            raise ConfigError("--chapter-range must be START:END, such as 2:5") from None
        if first < 1 or last < first:
            raise ConfigError("--chapter-range must be START:END with 1 <= START <= END")
        chosen |= set(range(first, last + 1))
    known = {chapter.number for chapter in manifest.chapters}
    if chosen - known:
        raise ConfigError("A selected chapter does not exist in this book")
    return [c for c in manifest.chapters if not chosen or c.number in chosen]


def _memory_bytes() -> int | None:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None


def _uses_cpu(device: str) -> bool:
    if device == "cpu":
        return True
    if device == "cuda":
        return False
    try:
        import torch

        return not torch.cuda.is_available()
    except Exception:
        return True


def _decode_all(
    items: list[_Chapter],
    folder: Path,
    results: dict[int, ChapterResult],
    models: Sequence[ModelName],
) -> list[_Chapter]:
    """Decode each chapter to a scratch WAV; a chapter that won't decode is reported, not fatal.

    The source MP3 is only read. Returns the chapters that decoded.
    """
    decoded: list[_Chapter] = []
    for item in items:
        try:
            item.wav = decode(
                item.reference.audio, folder / f"chapter-{item.chapter.number:04d}.wav"
            )
        except AudioError:
            results[item.chapter.number] = _unavailable(item.chapter, "audio_undecodable", models)
            continue
        item.duration = item.wav.stat().st_size / 32_000  # 16 kHz, 16-bit, mono
        decoded.append(item)
    return decoded


def _listen(
    model: ModelName,
    items: list[_Chapter],
    backend: AsrBackend,
    reporter: ProgressReporter,
    should_stop: Callable[[], bool],
) -> None:
    """Run one model over every chapter; a failure abstains for that chapter only."""
    handle = reporter.stage(f"Listening with {model}", len(items), "chapter")
    try:
        for position, item in enumerate(items, 1):
            handle.set_detail(f"chapter {position}/{len(items)}")
            if should_stop():
                raise Cancelled
            started = time.monotonic()
            try:
                assert item.wav is not None
                transcript = backend.transcribe(item.wav, should_stop=should_stop)
            except (Cancelled, KeyboardInterrupt):
                raise
            except Exception:
                item.runs[model] = ModelRun(model, "failed", "model_failed")
            else:
                item.transcripts[model] = transcript.words
                item.runs[model] = ModelRun(
                    model, "ok", None, time.monotonic() - started, len(transcript.words)
                )
            handle.advance()
    finally:
        handle.close()
        close = getattr(backend, "close", None)
        if callable(close):
            close()


def _result(item: _Chapter, models: Sequence[ModelName], cancelled: bool) -> ChapterResult:
    runs = tuple(
        item.runs.get(model)
        or ModelRun(model, "failed", "cancelled" if cancelled else "model_failed")
        for model in models
    )
    found: dict[ModelName, list[Difference]] = {}
    for model, words in item.transcripts.items():
        found[model] = compare.differences(model, item.tokens, compare.tokenize(words))
    flags = compare.vote(item.tokens, found)
    status, reason, partial = compare.chapter_outcome(runs, flags)
    # Audio that changed while it was being heard can't be judged against these transcripts.
    if digest_file(item.reference.audio) != item.reference.audio_sha256:
        status, reason, partial, flags = "verification_unavailable", "audio_stale", True, []
    return ChapterResult(
        number=item.chapter.number,
        status=status,
        reason=reason,
        models=runs,
        flags=tuple(flags),
        partial=partial,
        audio_sha256=item.reference.audio_sha256,
        reference_sha256=item.reference.sha256,
        duration_seconds=item.duration,
        transcripts=dict(item.transcripts),
    )


def _unavailable(chapter: Chapter, reason: str, models: Sequence[ModelName]) -> ChapterResult:
    return ChapterResult(
        chapter.number,
        "verification_unavailable",
        reason,
        tuple(ModelRun(m, "unavailable", reason) for m in models),
        partial=True,
    )


def previous_chapters(workspace: Path) -> dict[int, dict[str, Any]]:
    """Chapter results from an earlier report; an absent or malformed report has none."""
    data = load_bounded_json(workspace / REPORT, max_bytes=REPORT_MAX_BYTES, max_depth=16)
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != 1
        or not isinstance(data.get("chapters"), list)
    ):
        return {}
    return {
        c["number"]: c
        for c in data["chapters"]
        if isinstance(c, dict) and isinstance(c.get("number"), int)
    }


def _flag_key(flag: dict[str, Any]) -> tuple[Any, ...]:
    return (flag.get("kind"), flag.get("ref_start"), flag.get("ref_end"), flag.get("expected"))


def keep_reviewed(old: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    """Carry "reviewed" marks to the same flags found again in the same audio (spec §6)."""
    if not old or old.get("audio_sha256") != new.get("audio_sha256"):
        return new
    reviewed = {
        _flag_key(f) for f in old.get("flags", []) if isinstance(f, dict) and f.get("reviewed")
    }
    for flag in new["flags"]:
        if _flag_key(flag) in reviewed:
            flag["reviewed"] = True
    return new


def _saved(workspace: Path) -> dict[str, Any] | None:
    data = load_bounded_json(workspace / REPORT, max_bytes=REPORT_MAX_BYTES, max_depth=16)
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != 1
        or not isinstance(data.get("chapters"), list)
    ):
        return None
    return data


def saved_report(workspace: Path) -> dict[str, Any] | None:
    """The saved report for display, if present and of this version; never raises for bad files.

    Reads never show full transcripts, whichever run kept them (AVF2): the copy has none and
    says so in its retention field.
    """
    data = _saved(workspace)
    if data is None:
        return None
    chapters = [without_transcripts(c) if isinstance(c, dict) else c for c in data["chapters"]]
    return {**data, "chapters": chapters, "keep_transcripts": False}


def mark_reviewed(workspace: Path, number: int, index: int, *, reviewed: bool = True) -> None:
    """Mark one flag of a chapter's saved result reviewed (or not); no audio or text changes."""
    # Rewrites the file as it is: a review mark is not a verification run (AVF2).
    report = _saved(workspace)
    chapter = next(
        (
            c
            for c in (report or {}).get("chapters", [])
            if isinstance(c, dict) and c.get("number") == number
        ),
        None,
    )
    flags = chapter.get("flags") if isinstance(chapter, dict) else None
    if report is None or not isinstance(flags, list) or not 0 <= index < len(flags):
        raise ConfigError("That chapter has no such flag in the saved verification report")
    flags[index]["reviewed"] = reviewed
    write_json(workspace / REPORT, report)


def verify_book(
    workspace: Path,
    manifest: BookManifest,
    settings: Settings,
    chapters: Sequence[Chapter],
    *,
    models: Sequence[ModelName] = MODEL_NAMES,
    device: str = "auto",
    keep_transcripts: bool = False,
    reporter: ProgressReporter | None = None,
    should_stop: Callable[[], bool] = lambda: False,
    backend_factory: BackendFactory | None = None,
) -> dict[str, Any]:
    """Verify `chapters` and write `reports/audio_verification.json`; return the report.

    The caller holds the workspace lock. On interruption the report is written with what
    finished, then the interruption is raised again.
    """
    reporter = reporter or NullReporter()
    factory = backend_factory or (lambda name: make_backend(name, device=device))
    created = datetime.now(UTC).isoformat(timespec="seconds")
    warnings: list[str] = []
    backends = {name: factory(name) for name in models}
    states: dict[ModelName, Readiness] = {name: b.readiness() for name, b in backends.items()}
    ready = [name for name in models if states[name].ready]
    if "whisper" in ready and _uses_cpu(device):
        memory = _memory_bytes()
        if memory is not None and memory < WHISPER_CPU_RAM_BYTES:
            warnings.append("whisper_low_memory")
    results: dict[int, ChapterResult] = {}
    items: list[_Chapter] = []
    for chapter in chapters:
        reference = chapter_reference(workspace, manifest, chapter, settings)
        if isinstance(reference, Unavailable):
            results[chapter.number] = _unavailable(chapter, reference.reason, models)
        elif not reference.exact:
            # Not what the speech engine was given: no model listens, nothing is voted (AVF1).
            results[chapter.number] = _unavailable(chapter, "narration_not_spoken", models)
        else:
            items.append(_Chapter(chapter, reference, compare.tokenize_text(reference.text)))
    for item in items:
        for name in models:
            if not states[name].ready:
                item.runs[name] = ModelRun(name, "unavailable", states[name].reason)
    interrupted: BaseException | None = None
    if items and ready and shutil.which("ffmpeg") is None:
        # Every chapter needs FFmpeg to decode; say so once, not per chapter (AVF4).
        warnings.append("ffmpeg_missing")
    with tempfile.TemporaryDirectory(prefix="verify-") as scratch:
        try:
            if items and ready:
                items = _decode_all(items, Path(scratch), results, models)
            for name in ready:
                _listen(name, items, backends[name], reporter, should_stop)
        except (Cancelled, KeyboardInterrupt) as stop:
            interrupted = stop
        for item in items:
            results[item.chapter.number] = _result(item, models, interrupted is not None)
    previous = previous_chapters(workspace)
    tokens = {item.chapter.number: item.tokens for item in items}
    for number, result in results.items():
        fresh = chapter_json(result, tokens.get(number, []), keep_transcripts=keep_transcripts)
        previous[number] = keep_reviewed(previous.get(number), fresh)
    merged = [previous[n] for n in sorted(previous)]
    # Retention is this run's explicit choice (AVF2): chapters this run didn't verify must not
    # keep full transcripts from an earlier retaining run.
    if not keep_transcripts:
        merged = [without_transcripts(chapter) for chapter in merged]
    report = report_json(
        merged,
        [states[name] for name in models],
        created_at=created,
        completed_at=None if interrupted else datetime.now(UTC).isoformat(timespec="seconds"),
        keep_transcripts=retains_transcripts(merged),
        warnings=warnings,
    )
    try:
        write_json(workspace / REPORT, report)
    except (OSError, ValueError):
        raise AudioError("Could not write the audio verification report") from None
    if isinstance(interrupted, KeyboardInterrupt):
        raise interrupted
    if isinstance(interrupted, Cancelled):
        raise KeyboardInterrupt
    return report


def stale_chapters(
    workspace: Path, manifest: BookManifest, settings: Settings, report: dict[str, Any]
) -> set[int]:
    """Chapters whose saved result no longer matches their audio or expected narration.

    A result is stale once the chapter's MP3 or its narration (text, pronunciations, voice
    markers) changes (spec §5); it is then shown as stale, not as current evidence.
    """
    by_number = {chapter.number: chapter for chapter in manifest.chapters}
    stale: set[int] = set()
    # Results judged with other model revisions than the pinned ones are all stale.
    from pdf2audiobook.verification.models import SPECS

    pinned = {name: spec.revision for name, spec in SPECS.items()}
    if any(
        isinstance(m, dict) and pinned.get(m.get("model")) not in (None, m.get("revision"))  # type: ignore[arg-type]
        for m in report.get("models", [])
    ):
        return {
            entry["number"]
            for entry in report.get("chapters", [])
            if isinstance(entry, dict) and isinstance(entry.get("number"), int)
        }
    for entry in report.get("chapters", []):
        if not isinstance(entry, dict) or entry.get("audio_sha256") is None:
            continue
        chapter = by_number.get(entry.get("number"))  # type: ignore[arg-type]
        reference = chapter_reference(workspace, manifest, chapter, settings) if chapter else None
        if (
            not isinstance(reference, Reference)
            or not reference.exact
            or (
                reference.audio_sha256 != entry["audio_sha256"]
                or reference.sha256 != entry.get("reference_sha256")
            )
        ):
            stale.add(entry["number"])
    return stale
