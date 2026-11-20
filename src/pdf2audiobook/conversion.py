"""Chapter conversion orchestration with explicit replaceable dependencies."""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from pdf2audiobook.audio import AudioEncoder
from pdf2audiobook.audio.commit import (
    commit_chapter_audio,
    discard_staged,
    recover_audio_commits,
    staged_path,
)
from pdf2audiobook.config import Settings
from pdf2audiobook.errors import AudioError, PartialConversionError
from pdf2audiobook.models import BookManifest, Chapter
from pdf2audiobook.progress_display import ProgressHandle, ProgressReporter
from pdf2audiobook.tts import TTSProvider
from pdf2audiobook.workspace import fingerprint, write_json

if TYPE_CHECKING:
    from pdf2audiobook.tts.cloning import ReferenceVoice


@dataclass(frozen=True)
class ConversionServices:
    log_event: Callable[..., Any]
    read_manifest: Callable[..., Any]
    prepare_chapter_selection: Callable[..., Any]
    render_chapter_texts: Callable[..., Any]
    create_tts_provider: Callable[..., Any]
    synthesize_chunks: Callable[..., Any]
    encode_mp3: Callable[..., Any]
    chapter_audio_fingerprint: Callable[..., Any]
    audio_output_path: Callable[..., Any]
    read_synthesis_progress: Callable[..., Any]
    valid_mp3_sidecar: Callable[..., Any]
    tts_selection: Callable[..., Any]
    voice_marker_ids: Callable[..., Any]
    unspeakable_pause_ranges: Callable[..., Any]
    _tts_model_identity: Callable[..., Any]
    _progress_report_fields: Callable[..., Any]


def _rendering_inputs(settings: Settings) -> dict[str, object]:
    """Narration inputs recorded beside the audio; optional keys appear only when set."""
    inputs: dict[str, object] = {"footnotes": settings.pdf.footnotes}
    if settings.reading.process_citations:
        inputs["citations"] = True
    if settings.tts.voice_clone.enabled:
        from pdf2audiobook.tts.cloning import clone_metadata

        metadata = clone_metadata(settings)
        if metadata is not None:
            inputs["voice_clone"] = metadata
    return inputs


# (chapter, MP3 output, chapter text file, sidecar record, audio identity).
_PendingChapter = tuple[Chapter, Path, Path, Path, str]


@dataclass
class _ConversionRun:
    """Inputs and shared state for one book conversion.

    The keyword parameters of `_convert_analyzed_book` are gathered here.
    `provider` is created lazily and then shared by every step; the
    preflight maps, `conversion_status` and `failed_chapters` are filled in
    step order and become `conversion_status.json`.
    """

    manifest_path: Path
    settings: Settings
    cover_image: tuple[bytes, str] | None
    cover_identity: str | None
    force: bool
    encoder: AudioEncoder | None
    services: ConversionServices
    progress: ProgressReporter | None
    citation_kwargs: dict[str, Any]
    adapters: tuple[str, ...]
    manifest: BookManifest
    chosen: list[Chapter]
    skipped_empty: set[str]
    provider: TTSProvider | None
    preflight_failed: dict[int, int] = field(default_factory=dict)
    preflight_reasons: dict[int, str] = field(default_factory=dict)
    conversion_status: dict[str, dict[str, object]] = field(default_factory=dict)
    failed_chapters: set[int] = field(default_factory=set)

    def text_file(self, item: Chapter) -> Path:
        """The approved chapter text file for a chapter."""
        return self.manifest_path.parent / "chapters" / f"{item.number:03d}.txt"


def _remove_stale_temporary_audio(manifest_path: Path) -> None:
    """Delete chapter WAVs a previous run left behind."""
    temporary_wav_dir = manifest_path.parent / ".cache" / "tts" / "chapters"
    try:
        if temporary_wav_dir.is_dir():
            for stale_wav in temporary_wav_dir.glob("chapter-*.wav"):
                stale_wav.unlink(missing_ok=True)
    except OSError:
        raise AudioError("Could not clean stale temporary chapter audio") from None


def _read_voice_markers(run: _ConversionRun) -> dict[int, list[str]]:
    """Read each chapter's voice markers, failing chapters that can't use them.

    Returns the marker ids per manually approved chapter. A misplaced marker,
    or markers in an unapproved chapter, fails only that chapter.
    """
    approved_marker_chapters: dict[int, list[str]] = {}
    for item in run.chosen:
        if item.id in run.skipped_empty:
            continue
        try:
            chapter_source = run.text_file(item).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise AudioError("Cannot read approved chapter text; check workspace files") from None
        try:
            marker_ids = run.services.voice_marker_ids(chapter_source)
        except AudioError:
            # A misplaced marker fails its own chapter, not the whole book.
            run.preflight_failed[item.number] = AudioError.exit_code
            run.preflight_reasons[item.number] = "invalid_voice_marker"
            continue
        if marker_ids and not item.manually_approved:
            run.preflight_failed[item.number] = AudioError.exit_code
        elif marker_ids:
            approved_marker_chapters[item.number] = marker_ids
    return approved_marker_chapters


def _preflight_voice_markers(run: _ConversionRun) -> None:
    """Fail chapters whose voice markers name voices the engine doesn't list."""
    approved_marker_chapters = _read_voice_markers(run)
    all_marker_ids = {marker for markers in approved_marker_chapters.values() for marker in markers}
    if not all_marker_ids:
        return
    try:
        if run.provider is None:
            run.provider = run.services.create_tts_provider(run.settings)
        provider = run.provider
        supports_voice_listing = getattr(provider, "supports_voice_listing", True) is not False
        if supports_voice_listing:
            voice_list = provider.list_voices()
            if not isinstance(voice_list, list) or any(
                not isinstance(voice, str) for voice in voice_list
            ):
                raise AudioError("Voice list is unavailable")
            available_voices = voice_list
        else:
            available_voices = None
    except Exception:
        available_voices = None
        for item in run.chosen:
            if approved_marker_chapters.get(item.number):
                run.preflight_failed[item.number] = AudioError.exit_code
                run.preflight_reasons[item.number] = "voice_list_unavailable"
    if available_voices is not None:
        for item in run.chosen:
            marker_ids = approved_marker_chapters.get(item.number, [])
            if any(marker not in available_voices for marker in marker_ids):
                run.preflight_failed[item.number] = AudioError.exit_code
                run.preflight_reasons[item.number] = "invalid_voice_marker"


def _initial_status(run: _ConversionRun) -> None:
    """Start every chosen chapter as skipped, failed in preflight or pending."""
    run.failed_chapters = set(run.preflight_failed)
    run.conversion_status = {
        item.id: {
            "number": item.number,
            "status": (
                "skipped"
                if item.id in run.skipped_empty
                else "failed"
                if item.number in run.preflight_failed
                else "pending"
            ),
            **({"reason_code": "empty_chapter"} if item.id in run.skipped_empty else {}),
            **({"error_code": AudioError.exit_code} if item.number in run.preflight_failed else {}),
            **(
                {"reason_code": run.preflight_reasons[item.number]}
                if item.number in run.preflight_reasons
                else {}
            ),
        }
        for item in run.chosen
    }


def _recorded_reference_matches(recorded: dict[str, Any], reference: ReferenceVoice) -> bool:
    """A finished clone stays valid while its reference audio and any supplied transcript match.

    The fresh identity records installed backend versions, so an optional package that is
    merely absent must not make finished audio stale. Validation still rejects a recorded
    identity whose backend differs from an installed one.
    """
    if recorded["reference_audio_sha256"] != reference.identity["reference_audio_sha256"]:
        return False
    if reference.transcript is None:
        return True
    return recorded["reference_text_sha256"] == reference.identity["reference_text_sha256"]


def _recorded_clone(run: _ConversionRun) -> dict[str, Any] | None:
    from pdf2audiobook.tts.cloning import valid_recorded_identity

    found: dict[str, Any] | None = None
    for chapter in run.chosen:
        if chapter.id in run.skipped_empty:
            continue
        output = run.services.audio_output_path(run.manifest, chapter, run.manifest_path.parent)
        metadata = run.services.valid_mp3_sidecar(output)
        inputs = metadata.get("rendering_inputs") if isinstance(metadata, dict) else None
        clone = inputs.get("voice_clone") if isinstance(inputs, dict) else None
        if not valid_recorded_identity(clone) or (found is not None and found != clone):
            return None
        found = clone
    return found


def _previous_clone_selection(run: _ConversionRun) -> bool:
    """Retain repair intent even when the MP3 is corrupt or its chapter title changed."""
    from pdf2audiobook.jsonio import load_bounded_json

    chosen = {chapter.id for chapter in run.chosen}
    for path in (run.manifest_path.parent / "audio").glob("*.cache.json"):
        if path.is_symlink():
            continue
        metadata = load_bounded_json(path, max_bytes=4096, max_depth=8)
        if (
            not isinstance(metadata, dict)
            or not isinstance(metadata.get("chapter_id"), str)
            or metadata["chapter_id"] not in chosen
        ):
            continue
        inputs = metadata.get("rendering_inputs")
        if isinstance(inputs, dict) and inputs.get("voice_clone") is not None:
            return True
    return False


@contextlib.contextmanager
def _voice_run(run: _ConversionRun) -> Iterator[None]:
    from pdf2audiobook.tts.cloning import (
        ReferenceVoice,
        clone_error,
        complete_transcript,
        snapshot_reference,
        validate_clone_selection,
    )

    settings = run.settings
    validate_clone_selection(settings)
    owned_provider = run.provider is None
    reference: ReferenceVoice | None = None
    previous = settings._clone_reference
    preparation = None
    try:
        if settings.tts.voice_clone.enabled:
            if run.progress is not None and run.progress.enabled:
                preparation = run.progress.stage("Preparing voice reference", None, "reference")
            for chapter in run.chosen:
                if chapter.id in run.skipped_empty:
                    continue
                try:
                    text = run.text_file(chapter).read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    raise clone_error(
                        "Could not read the selected chapter text", "voice_selection_conflict"
                    ) from None
                if chapter.voice_id or run.services.voice_marker_ids(text):
                    raise clone_error(
                        f"Chapter {chapter.number} has a voice override; clear it or disable cloning",
                        "voice_selection_conflict",
                    )
            recorded = _recorded_clone(run) if settings.general.resume and not run.force else None
            configured = settings.tts.voice_clone.reference_audio or ""
            missing = (
                "://" not in configured
                and "\0" not in configured
                and not os.path.lexists(Path(configured).expanduser())
            )
            if missing and recorded is not None:
                reference = ReferenceVoice(recorded)
            else:
                reference = snapshot_reference(settings, transcribe=False)
                if recorded is not None and _recorded_reference_matches(recorded, reference):
                    reference.identity = recorded
                elif reference.transcript is None:
                    complete_transcript(reference)
            settings._clone_reference = reference
            if preparation is not None:
                preparation.close()
                preparation = None
        elif "enabled" not in settings._clone_explicit and _previous_clone_selection(run):
            raise clone_error(
                "This audio used a cloned voice; provide its reference or choose --no-clone-voice explicitly",
                "voice_selection_conflict",
            )
        yield
    finally:
        if preparation is not None:
            preparation.close()
        if owned_provider and run.provider is not None:
            close = getattr(run.provider, "close", None)
            if callable(close):
                close()
        if reference is not None:
            reference.close()
        settings._clone_reference = previous


def _chapter_identity(run: _ConversionRun, text: str, item: Chapter) -> str:
    """The audio identity of a chapter's text and every audible setting."""
    identity: str = run.services.chapter_audio_fingerprint(
        text,
        run.settings,
        run.manifest,
        item,
        run.adapters,
        cover_image=run.cover_image,
        cover_identity=run.cover_identity,
    )
    return identity


def _cache_files_ready(run: _ConversionRun, output: Path, record: Path) -> bool:
    """Whether a resumable MP3 and its sidecar exist and the MP3 is non-empty."""
    if not (run.settings.general.resume and not run.force):
        return False
    # A file can disappear or become unreadable between is_file()
    # and stat(). Treat this as a cache miss, not a book-path error.
    try:
        return output.is_file() and output.stat().st_size > 0 and record.is_file()
    except OSError:
        return False


def _reusable_audio(run: _ConversionRun, item: Chapter, output: Path, identity: str) -> bool:
    """Whether an existing MP3 matches the identity, its sidecar and its own tags."""
    manifest = run.manifest
    try:
        from mutagen import MutagenError
        from mutagen.easyid3 import EasyID3
        from mutagen.mp3 import MP3

        metadata = run.services.valid_mp3_sidecar(output)
        cached = (
            isinstance(metadata, dict)
            and metadata.get("fingerprint") == identity
            and metadata.get("chapter_id", item.id) == item.id
            and metadata.get("rendering_inputs") == _rendering_inputs(run.settings)
        )
        if cached:
            mp3 = MP3(output, ID3=EasyID3)
            tags = mp3.tags
            # The sidecar is not sufficient evidence of correct chapter
            # identity: verify the actual audio tags before reusing it.
            cached = (
                mp3.info is not None
                and mp3.info.length > 0
                and tags is not None
                and tags.get("title") == [item.title]
                and tags.get("album") == [manifest.title]
                and tags.get("tracknumber") == [str(item.number)]
                and (not manifest.author or tags.get("artist") == [manifest.author])
            )
    except (OSError, ValueError, MutagenError):
        # A corrupt MP3, even with a matching cache sidecar checksum,
        # must be regenerated rather than aborting the entire book.
        cached = False
    return cached


def _plan_synthesis(
    run: _ConversionRun,
) -> tuple[list[Path], list[_PendingChapter], dict[str, int], int]:
    """Decide which chapters reuse their MP3 and which need synthesis.

    Returns every output path, the pending chapters, the text length per
    chapter and the length of the reused chapters' text.
    """
    # Audio identities include all audible and encoding settings, not merely the PDF hash.
    pending: list[_PendingChapter] = []
    outputs = []
    chapter_chars: dict[str, int] = {}
    cached_chars = 0
    for item in run.chosen:
        if item.id in run.skipped_empty:
            continue
        output = run.services.audio_output_path(run.manifest, item, run.manifest_path.parent)
        outputs.append(output)
        if item.number in run.preflight_failed:
            continue
        text_file = run.text_file(item)
        try:
            text = text_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            # PDF-derived filenames and source text must not escape in errors.
            raise AudioError("Cannot read approved chapter text; check workspace files") from None
        identity = _chapter_identity(run, text, item)
        chapter_chars[item.id] = len(text)
        record = output.with_suffix(".cache.json")
        cached = _cache_files_ready(run, output, record) and _reusable_audio(
            run, item, output, identity
        )
        if not cached:
            # Retain the path and identity, not the full text of every chapter.
            # A long book may have hundreds of pending chapters.
            pending.append((item, output, text_file, record, identity))
        else:
            cached_chars += len(text)
            run.conversion_status[item.id]["status"] = "complete"
            # A resumed chapter keeps the pause count its synthesized run reported.
            try:
                run.conversion_status[item.id]["pause_count"] = len(
                    run.services.unspeakable_pause_ranges(text, **run.citation_kwargs)
                )
            except AudioError:
                run.conversion_status[item.id]["pause_count"] = 0
        del text
    return outputs, pending, chapter_chars, cached_chars


def _synthesize_and_encode(
    run: _ConversionRun,
    item: Chapter,
    output: Path,
    text: str,
    selection: tuple[str, str, float],
    synth_kwargs: dict[str, Any],
) -> None:
    """Synthesize one chapter, encode its MP3 and record its pause report.

    `selection` is the (model identity, voice, speed) chosen for the chapter.
    """
    settings = run.settings
    services = run.services
    provider = run.provider
    assert provider is not None
    selected_model, selected_voice, selected_speed = selection
    progress_path = (
        run.manifest_path.parent
        / ".cache"
        / "tts"
        / "progress"
        / f"{fingerprint(item.id, item.number)[:32]}.json"
    )
    samples = services.synthesize_chunks(
        text,
        provider,
        # Chunk cache keys include the model; qualify it for injected engines.
        model=":".join((selected_model, *(a for a in run.adapters if a.startswith("tts=")))),
        voice=selected_voice,
        speed=selected_speed,
        pause_ms=settings.tts.pause_ms,
        pronunciations=settings.tts.pronunciations,
        max_retries=settings.tts.max_retries,
        cache=run.manifest_path.parent / ".cache" / "tts",
        use_cache=settings.cache.enabled and settings.general.resume and not run.force,
        progress_file=progress_path,
        **synth_kwargs,
    )
    encode = services.encode_mp3 if run.encoder is None else run.encoder
    # Encoded beside the chapters but not over them: the current MP3 stays until the new one
    # is checked and committed (`audio/commit.py`).
    try:
        staged_path(output).parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise AudioError("Could not create the chapter audio staging folder") from None
    encode(
        samples,
        provider.sample_rate,
        staged_path(output),
        bitrate=settings.tts.bitrate,
        target_rate=settings.tts.sample_rate,
        title=item.title,
        artist=run.manifest.author,
        album=run.manifest.title,
        track=item.number,
        cover_image=run.cover_image,
    )
    chapter_progress = services.read_synthesis_progress(progress_path)
    pause_count, mapping = services._progress_report_fields(chapter_progress)
    run.conversion_status[item.id]["pause_count"] = pause_count
    run.conversion_status[item.id]["chunk_mapping"] = mapping


def _fail_chapter(run: _ConversionRun, item: Chapter, *, keep_reason: bool) -> None:
    """Record a chapter's audio failure, keeping its preflight reason if asked."""
    run.failed_chapters.add(item.number)
    failure_status: dict[str, object] = {
        "number": item.number,
        "status": "failed",
        "error_code": AudioError.exit_code,
    }
    if keep_reason and item.number in run.preflight_reasons:
        failure_status["reason_code"] = run.preflight_reasons[item.number]
    run.conversion_status[item.id] = failure_status


def _remove_obsolete_audio(run: _ConversionRun, item: Chapter, output: Path) -> None:
    """Delete this chapter's older MP3s and sidecars, skipping anything uninspectable."""
    log_event = run.services.log_event
    for previous in output.parent.glob("*.mp3"):
        if previous == output:
            continue
        try:
            if os.path.samefile(previous, output):
                continue
        except OSError:
            log_event(
                "audio_cleanup_candidate_skipped",
                level=logging.WARNING,
                reason="candidate_uninspectable",
            )
            continue
        try:
            metadata = run.services.valid_mp3_sidecar(previous)
            if metadata is None or metadata.get("chapter_id") != item.id:
                continue
            previous.unlink()
            previous.with_suffix(".cache.json").unlink(missing_ok=True)
        except OSError:
            log_event(
                "audio_cleanup_candidate_skipped",
                level=logging.WARNING,
                reason="candidate_uninspectable",
            )


def _publish_chapter(
    run: _ConversionRun, item: Chapter, output: Path, record: Path, text: str, identity: str
) -> None:
    """Commit the chapter's new MP3 and sidecar, mark it complete and clean up its old audio.

    The previous MP3 and sidecar are kept under `audio/.backup/`; if committing fails, the
    chapter fails and its previous audio stays as it was.
    """
    try:
        commit_chapter_audio(
            output,
            record,
            {
                "chapter_id": item.id,
                "sidecar_version": 3,
                "rendering_inputs": _rendering_inputs(run.settings),
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "fingerprint": identity,
            },
        )
    except AudioError:
        _fail_chapter(run, item, keep_reason=False)
        return
    run.conversion_status[item.id]["status"] = "complete"
    run.services.log_event(
        "stage_completed", level=logging.INFO, stage="chapter_audio", count=item.number
    )
    _remove_obsolete_audio(run, item, output)


def _convert_chapter(
    run: _ConversionRun,
    entry: _PendingChapter,
    position: int,
    total: int,
    synthesis: ProgressHandle | None,
) -> None:
    """Synthesize, encode and publish one pending chapter.

    An audio failure fails only this chapter; changed text since planning
    stops the book.
    """
    item, output, text_file, record, identity = entry
    try:
        text = text_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise AudioError("Cannot read approved chapter text; check workspace files") from None
    chunk_chars = [0]

    def settle(chapter_size: int = len(text), done: list[int] = chunk_chars) -> None:
        # Characters outside any spoken chunk (markers, blank lines) finish instantly.
        if synthesis is not None and done[0] < chapter_size:
            synthesis.advance(chapter_size - done[0], cached=True)
            done[0] = chapter_size

    if synthesis is not None:
        synthesis.set_detail(f"chapter {position}/{total}")
    # Detect edits between the cache-check and synthesis passes. Never
    # publish audio with a fingerprint computed from different prose.
    if _chapter_identity(run, text, item) != identity:
        raise AudioError("Approved chapter text changed during conversion; retry")
    if run.provider is None:
        try:
            run.provider = run.services.create_tts_provider(run.settings)
        except AudioError:
            settle()
            _fail_chapter(run, item, keep_reason=False)
            return
    selected_model = run.services._tts_model_identity(run.settings)
    _provider_name, selected_voice, selected_speed = run.services.tts_selection(run.settings, item)
    streamed_wav: Path | None = None
    try:
        synth_kwargs: dict[str, Any] = dict(run.citation_kwargs)
        if run.encoder is None:
            try:
                run.manifest_path.parent.joinpath(".cache", "tts", "chapters").mkdir(
                    parents=True, exist_ok=True
                )
                with tempfile.NamedTemporaryFile(
                    prefix="chapter-",
                    suffix=".wav",
                    dir=run.manifest_path.parent / ".cache" / "tts" / "chapters",
                    delete=False,
                ) as temp_wav:
                    streamed_wav = Path(temp_wav.name)
            except OSError:
                raise AudioError("Could not create temporary chapter audio") from None
            synth_kwargs["output_wav"] = streamed_wav
        if synthesis is not None:

            def on_chunk(characters: int, cached: bool, done: list[int] = chunk_chars) -> None:
                done[0] += characters
                if synthesis is not None:
                    synthesis.advance(characters, cached=cached)

            synth_kwargs["on_chunk"] = on_chunk
        _synthesize_and_encode(
            run, item, output, text, (selected_model, selected_voice, selected_speed), synth_kwargs
        )
    except AudioError:
        discard_staged(output)
        _fail_chapter(run, item, keep_reason=True)
        return
    except BaseException:
        # Interrupted: the current MP3 was never touched; drop the half-made one.
        discard_staged(output)
        raise
    finally:
        settle()
        if streamed_wav is not None:
            streamed_wav.unlink(missing_ok=True)
    _publish_chapter(run, item, output, record, text, identity)


def _write_conversion_status(run: _ConversionRun) -> None:
    """Write `conversion_status.json` with the book's total pause count."""
    pause_counts = [row.get("pause_count") for row in run.conversion_status.values()]
    total_pause_count = (
        sum(
            value
            for value in pause_counts
            if isinstance(value, int) and not isinstance(value, bool)
        )
        if all(isinstance(value, int) and not isinstance(value, bool) for value in pause_counts)
        else None
    )
    write_json(
        run.manifest_path.parent / "reports" / "conversion_status.json",
        {
            "schema_version": 1,
            "pause_count": total_pause_count,
            "chapters": sorted(
                run.conversion_status.values(),
                key=lambda value: value["number"] if isinstance(value.get("number"), int) else 0,
            ),
        },
    )


def _convert_analyzed_book(
    manifest_path: Path,
    settings: Settings,
    cover_image: tuple[bytes, str] | None,
    cover_identity: str | None,
    *,
    chapter: int | None,
    chapter_range: tuple[int, int] | None,
    force: bool,
    accept_review: tuple[str, ...],
    tts_provider: TTSProvider | None,
    encoder: AudioEncoder | None,
    services: ConversionServices,
    progress: ProgressReporter | None = None,
) -> list[Path]:
    """Convert the selected chapters of an analyzed book to MP3.

    Steps, in order: stale temporary audio, manifest and chapter selection
    (with review acknowledgements), voice-marker preflight, initial status,
    the reuse plan, per-chapter synthesis and publishing, then the status
    report. Dependencies are always called through `services`.
    """
    # Passed only when on, so injected synthesis doubles that predate it keep working.
    citation_kwargs: dict[str, Any] = (
        {"skip_citations": True} if settings.reading.process_citations else {}
    )
    _remove_stale_temporary_audio(manifest_path)
    # Finish a commit a stopped run journaled; drop unjournaled staged files.
    recover_audio_commits(manifest_path.parent / "audio")
    adapters = tuple(
        f"{role}={type(adapter).__module__}.{type(adapter).__qualname__}"
        for role, adapter in (("tts", tts_provider), ("encoder", encoder))
        if adapter is not None
    )
    manifest = services.read_manifest(manifest_path)
    selection = services.prepare_chapter_selection(
        manifest_path,
        manifest,
        settings,
        chapter=chapter,
        chapter_range=chapter_range,
        acknowledge=accept_review,
        persist=True,
    )
    services.render_chapter_texts(manifest, manifest_path.parent, settings.pdf.footnotes)
    run = _ConversionRun(
        manifest_path=manifest_path,
        settings=settings,
        cover_image=cover_image,
        cover_identity=cover_identity,
        force=force,
        encoder=encoder,
        services=services,
        progress=progress,
        citation_kwargs=citation_kwargs,
        adapters=adapters,
        manifest=manifest,
        chosen=selection.chapters,
        skipped_empty={item.id for item in selection.skipped},
        provider=tts_provider,
    )
    return _synthesize_selected(run)


def _synthesize_selected(run: _ConversionRun) -> list[Path]:
    settings, progress = run.settings, run.progress
    with _voice_run(run):
        _preflight_voice_markers(run)
        _initial_status(run)
        outputs, pending, chapter_chars, cached_chars = _plan_synthesis(run)
        if pending and settings.tts.voice_clone.enabled:
            from pdf2audiobook.tts.cloning import complete_transcript

            reference = settings._clone_reference
            if reference.transcript is None:
                recorded_digest = reference.identity.get("reference_text_sha256")
                complete_transcript(reference)
                _initial_status(run)
                outputs, pending, chapter_chars, cached_chars = _plan_synthesis(run)
                if reference.identity.get("reference_text_sha256") != recorded_digest:
                    for item, *_ in pending:
                        run.conversion_status[item.id]["reason_code"] = "voice_reference_changed"
        if (
            pending
            and run.provider is None
            and settings.tts.kitten.model in {"kitten2", "KittenML/kitten-tts-2"}
            and settings.tts.provider == "kitten"
        ):
            _prepare_kitten2(run)
        synthesis: ProgressHandle | None = None
        if progress is not None and progress.enabled and pending:
            # Characters, not chunks, so the estimate follows how much text is left.
            synthesis = progress.stage(
                "Synthesizing speech",
                sum(chapter_chars.values()),
                "char",
                initial=cached_chars,
            )
        for position, entry in enumerate(pending, 1):
            _convert_chapter(run, entry, position, len(pending), synthesis)
        if synthesis is not None:
            synthesis.close()
        _write_conversion_status(run)
        if run.failed_chapters:
            run.services.log_event(
                "degraded_output",
                level=logging.WARNING,
                stage="conversion",
                count=len(run.failed_chapters),
            )
            numbers = ", ".join(str(number) for number in sorted(run.failed_chapters))
            raise PartialConversionError(f"Chapter audio failed for chapter(s): {numbers}")
        return outputs


def _prepare_kitten2(run: _ConversionRun) -> None:
    """Load/condition once before chapter synthesis; preparation failures retain exit code 6."""
    from pdf2audiobook.tts.catalog import require_model

    stage = (
        run.progress.stage("Preparing local voice model", None, "model")
        if run.progress is not None and run.progress.enabled
        else None
    )
    try:
        require_model()
        run.provider = run.services.create_tts_provider(run.settings)
    finally:
        if stage is not None:
            stage.close()
