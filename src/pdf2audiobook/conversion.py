"""Chapter conversion orchestration with explicit replaceable dependencies."""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pdf2audiobook.audio import AudioEncoder
from pdf2audiobook.config import Settings
from pdf2audiobook.errors import AudioError, PartialConversionError
from pdf2audiobook.tts import TTSProvider
from pdf2audiobook.workspace import digest_file, fingerprint, write_json


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
) -> list[Path]:
    log_event = services.log_event
    read_manifest = services.read_manifest
    prepare_chapter_selection = services.prepare_chapter_selection
    render_chapter_texts = services.render_chapter_texts
    create_tts_provider = services.create_tts_provider
    synthesize_chunks = services.synthesize_chunks
    encode_mp3 = services.encode_mp3
    chapter_audio_fingerprint = services.chapter_audio_fingerprint
    audio_output_path = services.audio_output_path
    read_synthesis_progress = services.read_synthesis_progress
    valid_mp3_sidecar = services.valid_mp3_sidecar
    tts_selection = services.tts_selection
    voice_marker_ids = services.voice_marker_ids
    unspeakable_pause_ranges = services.unspeakable_pause_ranges
    _tts_model_identity = services._tts_model_identity
    _progress_report_fields = services._progress_report_fields
    temporary_wav_dir = manifest_path.parent / ".cache" / "tts" / "chapters"
    try:
        if temporary_wav_dir.is_dir():
            for stale_wav in temporary_wav_dir.glob("chapter-*.wav"):
                stale_wav.unlink(missing_ok=True)
    except OSError:
        raise AudioError("Could not clean stale temporary chapter audio") from None
    adapters = tuple(
        f"{role}={type(adapter).__module__}.{type(adapter).__qualname__}"
        for role, adapter in (("tts", tts_provider), ("encoder", encoder))
        if adapter is not None
    )
    manifest = read_manifest(manifest_path)
    selection = prepare_chapter_selection(
        manifest_path,
        manifest,
        settings,
        chapter=chapter,
        chapter_range=chapter_range,
        acknowledge=accept_review,
        persist=True,
    )
    render_chapter_texts(manifest, manifest_path.parent, settings.pdf.footnotes)
    chosen = selection.chapters
    skipped_empty = {item.id for item in selection.skipped}
    preflight_failed: dict[int, int] = {}
    preflight_reasons: dict[int, str] = {}
    approved_marker_chapters: dict[int, list[str]] = {}
    for item in chosen:
        if item.id in skipped_empty:
            continue
        text_file = manifest_path.parent / "chapters" / f"{item.number:03d}.txt"
        try:
            chapter_source = text_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise AudioError("Cannot read approved chapter text; check workspace files") from None
        try:
            marker_ids = voice_marker_ids(chapter_source)
        except AudioError:
            # A misplaced marker fails its own chapter, not the whole book.
            preflight_failed[item.number] = AudioError.exit_code
            preflight_reasons[item.number] = "invalid_voice_marker"
            continue
        if marker_ids and not item.manually_approved:
            preflight_failed[item.number] = AudioError.exit_code
        elif marker_ids:
            approved_marker_chapters[item.number] = marker_ids
    provider = tts_provider
    all_marker_ids = {marker for markers in approved_marker_chapters.values() for marker in markers}
    if all_marker_ids:
        try:
            if provider is None:
                provider = create_tts_provider(settings)
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
            for item in chosen:
                if approved_marker_chapters.get(item.number):
                    preflight_failed[item.number] = AudioError.exit_code
                    preflight_reasons[item.number] = "voice_list_unavailable"
        if available_voices is not None:
            for item in chosen:
                marker_ids = approved_marker_chapters.get(item.number, [])
                if any(marker not in available_voices for marker in marker_ids):
                    preflight_failed[item.number] = AudioError.exit_code
                    preflight_reasons[item.number] = "invalid_voice_marker"
    # Audio identities include all audible and encoding settings, not merely the PDF hash.
    pending = []
    outputs = []
    failed_chapters = set(preflight_failed)
    conversion_status: dict[str, dict[str, object]] = {
        item.id: {
            "number": item.number,
            "status": (
                "skipped"
                if item.id in skipped_empty
                else "failed"
                if item.number in preflight_failed
                else "pending"
            ),
            **({"reason_code": "empty_chapter"} if item.id in skipped_empty else {}),
            **({"error_code": AudioError.exit_code} if item.number in preflight_failed else {}),
            **(
                {"reason_code": preflight_reasons[item.number]}
                if item.number in preflight_reasons
                else {}
            ),
        }
        for item in chosen
    }
    for item in chosen:
        if item.id in skipped_empty:
            continue
        output = audio_output_path(manifest, item, manifest_path.parent)
        outputs.append(output)
        if item.number in preflight_failed:
            continue
        text_file = manifest_path.parent / "chapters" / f"{item.number:03d}.txt"
        try:
            text = text_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            # PDF-derived filenames and source text must not escape in errors.
            raise AudioError("Cannot read approved chapter text; check workspace files") from None
        identity = chapter_audio_fingerprint(
            text,
            settings,
            manifest,
            item,
            adapters,
            cover_image=cover_image,
            cover_identity=cover_identity,
        )
        record = output.with_suffix(".cache.json")
        cached = False
        if settings.general.resume and not force:
            # A file can disappear or become unreadable between is_file()
            # and stat(). Treat this as a cache miss, not a book-path error.
            try:
                cache_files_ready = (
                    output.is_file() and output.stat().st_size > 0 and record.is_file()
                )
            except OSError:
                cache_files_ready = False
        else:
            cache_files_ready = False
        if cache_files_ready:
            try:
                from mutagen import MutagenError
                from mutagen.easyid3 import EasyID3
                from mutagen.mp3 import MP3

                metadata = valid_mp3_sidecar(output)
                cached = (
                    isinstance(metadata, dict)
                    and metadata.get("fingerprint") == identity
                    and metadata.get("chapter_id", item.id) == item.id
                    and metadata.get("rendering_inputs") == {"footnotes": settings.pdf.footnotes}
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
        if not cached:
            # Retain the path and identity, not the full text of every chapter.
            # A long book may have hundreds of pending chapters.
            pending.append((item, output, text_file, record, identity))
        else:
            conversion_status[item.id]["status"] = "complete"
            # A resumed chapter keeps the pause count its synthesized run reported.
            try:
                conversion_status[item.id]["pause_count"] = len(unspeakable_pause_ranges(text))
            except AudioError:
                conversion_status[item.id]["pause_count"] = 0
        del text

    encode = encode_mp3 if encoder is None else encoder
    for item, output, text_file, record, identity in pending:
        try:
            text = text_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise AudioError("Cannot read approved chapter text; check workspace files") from None
        # Detect edits between the cache-check and synthesis passes. Never
        # publish audio with a fingerprint computed from different prose.
        if (
            chapter_audio_fingerprint(
                text,
                settings,
                manifest,
                item,
                adapters,
                cover_image=cover_image,
                cover_identity=cover_identity,
            )
            != identity
        ):
            raise AudioError("Approved chapter text changed during conversion; retry")
        if provider is None:
            try:
                provider = create_tts_provider(settings)
            except AudioError:
                failed_chapters.add(item.number)
                conversion_status[item.id] = {
                    "number": item.number,
                    "status": "failed",
                    "error_code": AudioError.exit_code,
                }
                continue
        selected_model = _tts_model_identity(settings)
        _provider_name, selected_voice, selected_speed = tts_selection(settings, item)
        streamed_wav: Path | None = None
        try:
            synth_kwargs = {}
            if encoder is None:
                try:
                    manifest_path.parent.joinpath(".cache", "tts", "chapters").mkdir(
                        parents=True, exist_ok=True
                    )
                    with tempfile.NamedTemporaryFile(
                        prefix="chapter-",
                        suffix=".wav",
                        dir=manifest_path.parent / ".cache" / "tts" / "chapters",
                        delete=False,
                    ) as temp_wav:
                        streamed_wav = Path(temp_wav.name)
                except OSError:
                    raise AudioError("Could not create temporary chapter audio") from None
                synth_kwargs["output_wav"] = streamed_wav
            progress_path = (
                manifest_path.parent
                / ".cache"
                / "tts"
                / "progress"
                / f"{fingerprint(item.id, item.number)[:32]}.json"
            )
            samples = synthesize_chunks(
                text,
                provider,
                # Chunk cache keys include the model; qualify it for injected engines.
                model=":".join((selected_model, *(a for a in adapters if a.startswith("tts=")))),
                voice=selected_voice,
                speed=selected_speed,
                pause_ms=settings.tts.pause_ms,
                pronunciations=settings.tts.pronunciations,
                max_retries=settings.tts.max_retries,
                cache=manifest_path.parent / ".cache" / "tts",
                use_cache=settings.cache.enabled and settings.general.resume and not force,
                progress_file=progress_path,
                **synth_kwargs,
            )
            encode(
                samples,
                provider.sample_rate,
                output,
                bitrate=settings.tts.bitrate,
                target_rate=settings.tts.sample_rate,
                title=item.title,
                artist=manifest.author,
                album=manifest.title,
                track=item.number,
                cover_image=cover_image,
            )
            progress = read_synthesis_progress(progress_path)
            pause_count, mapping = _progress_report_fields(progress)
            conversion_status[item.id]["pause_count"] = pause_count
            conversion_status[item.id]["chunk_mapping"] = mapping
        except AudioError:
            failed_chapters.add(item.number)
            failure_status: dict[str, object] = {
                "number": item.number,
                "status": "failed",
                "error_code": AudioError.exit_code,
            }
            if item.number in preflight_reasons:
                failure_status["reason_code"] = preflight_reasons[item.number]
            conversion_status[item.id] = failure_status
            continue
        finally:
            if streamed_wav is not None:
                streamed_wav.unlink(missing_ok=True)
        write_json(
            record,
            {
                "chapter_id": item.id,
                "sidecar_version": 3,
                "rendering_inputs": {"footnotes": settings.pdf.footnotes},
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "fingerprint": identity,
                "sha256": digest_file(output),
                "bytes": output.stat().st_size,
            },
        )
        conversion_status[item.id]["status"] = "complete"
        log_event("stage_completed", level=logging.INFO, stage="chapter_audio", count=item.number)
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
                metadata = valid_mp3_sidecar(previous)
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
    pause_counts = [row.get("pause_count") for row in conversion_status.values()]
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
        manifest_path.parent / "reports" / "conversion_status.json",
        {
            "schema_version": 1,
            "pause_count": total_pause_count,
            "chapters": sorted(
                conversion_status.values(),
                key=lambda value: value["number"] if isinstance(value.get("number"), int) else 0,
            ),
        },
    )
    if failed_chapters:
        log_event(
            "degraded_output", level=logging.WARNING, stage="conversion", count=len(failed_chapters)
        )
        numbers = ", ".join(str(number) for number in sorted(failed_chapters))
        raise PartialConversionError(f"Chapter audio failed for chapter(s): {numbers}")
    return outputs
