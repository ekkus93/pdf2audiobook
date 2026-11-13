"""Audio chunk generation, caching, and single-encode chapter MP3 assembly."""

from __future__ import annotations

import io
import math
import re
import shutil as shutil
import subprocess as subprocess
import tempfile as tempfile
import time
import wave
from functools import partial
from pathlib import Path
from typing import Any, Callable, Mapping, cast

import numpy as np

from pdf2audiobook.audio.citations import mask_citations as mask_citations
from pdf2audiobook.audio.encoding import (
    AudioEncoder as AudioEncoder,
)
from pdf2audiobook.audio.encoding import (
    _ffmetadata_value as _ffmetadata_value,
)
from pdf2audiobook.audio.encoding import (
    _safe_chapter_workspace as _safe_chapter_workspace,
)
from pdf2audiobook.audio.encoding import (
    _validate_chapter_wav as _validate_chapter_wav,
)
from pdf2audiobook.audio.encoding import (
    _write_chapter_wav as _write_chapter_wav,
)
from pdf2audiobook.audio.encoding import (
    encode_m4b as encode_m4b,
)
from pdf2audiobook.audio.encoding import (
    encode_mp3 as encode_mp3,
)
from pdf2audiobook.audio.progress import (
    _MAX_PROGRESS_RECORD_BYTES as _MAX_PROGRESS_RECORD_BYTES,
)
from pdf2audiobook.audio.progress import (
    _append_progress_update,
    _start_progress_stream,
    _SynthesisProgress,
    _write_progress_record,
)
from pdf2audiobook.audio.progress import (
    read_synthesis_progress as read_synthesis_progress,
)
from pdf2audiobook.audio.speech_text import (
    _voice_markers,
)
from pdf2audiobook.audio.speech_text import (
    chunk_source_ranges as chunk_source_ranges,
)
from pdf2audiobook.audio.speech_text import (
    has_speakable_chapter_narration as has_speakable_chapter_narration,
)
from pdf2audiobook.audio.speech_text import (
    has_speakable_narration as has_speakable_narration,
)
from pdf2audiobook.audio.speech_text import (
    split_sentences as split_sentences,
)
from pdf2audiobook.audio.speech_text import (
    unspeakable_pause_ranges as unspeakable_pause_ranges,
)
from pdf2audiobook.audio.speech_text import (
    voice_marker_ids as voice_marker_ids,
)
from pdf2audiobook.audio.wav import (
    _BoundedWavWriter,
    _open_streaming_wav,
    _write_pcm_chunk,
    _write_silence,
)
from pdf2audiobook.errors import AudioError, ConfigError
from pdf2audiobook.jsonio import load_bounded_json
from pdf2audiobook.models import BookManifest, Chapter
from pdf2audiobook.narration import (
    TTS_CHUNK_TEXT_NORMALIZATION_VERSION,
)
from pdf2audiobook.narration import (
    normalize_narration_text as normalize_narration_text,
)
from pdf2audiobook.tts import TTSProvider
from pdf2audiobook.workspace import atomic_write, digest_bytes, fingerprint, write_json

# Short TTS chunks must never require a 128 MiB WAV cache entry.
_MAX_CACHED_WAV_BYTES = 128 * 1024 * 1024
_MAX_COVER_BYTES = 5 * 1024 * 1024


def read_cover_image(path: str | Path | None) -> tuple[bytes, str] | None:
    """Read a bounded JPEG/PNG cover using signatures, with content-free errors."""
    if path is None:
        return None
    try:
        with Path(path).expanduser().open("rb") as source:
            data = source.read(_MAX_COVER_BYTES + 1)
    except OSError:
        raise ConfigError("Cover image is unavailable; check the configured image file") from None
    if len(data) > _MAX_COVER_BYTES:
        raise ConfigError("Cover image exceeds the 5 MiB limit")
    if data.startswith(b"\xff\xd8\xff"):
        return data, "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return data, "image/png"
    raise ConfigError("Cover image must be a JPEG or PNG file")


def wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    if (
        isinstance(sample_rate, bool)
        or not isinstance(sample_rate, int)
        or not 8000 <= sample_rate <= 192000
    ):
        raise AudioError("Audio sample_rate must be an integer from 8000 to 192000")
    try:
        audio = np.asarray(samples, dtype=np.float32)
    except Exception:
        # Untrusted TTS arrays and third-party conversion exceptions may echo
        # the source text. Report only a stable, non-content-bearing error.
        raise AudioError("TTS returned invalid audio sample data") from None
    # A multichannel buffer must not be silently flattened into a mono WAV:
    # doing so interleaves channels and changes playback speed and duration.
    if audio.ndim != 1:
        raise AudioError("TTS audio must be a one-dimensional mono sample buffer")
    # Enforce the same bounded WAV contract for direct callers before any
    # full-buffer scan, PCM allocation or serialization.
    if audio.size > (_MAX_CACHED_WAV_BYTES - 44) // 2:
        raise AudioError("TTS chunk exceeds safe WAV cache limit")
    if audio.size == 0 or not np.isfinite(audio).all():
        raise AudioError("TTS returned empty/nonfinite audio samples")
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(pcm.tobytes())
    return buffer.getvalue()


def read_wav(data: bytes, expected_rate: int) -> np.ndarray:
    if len(data) > _MAX_CACHED_WAV_BYTES:
        raise AudioError("Cached WAV exceeds safe size limit")
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            if (
                wav.getframerate() != expected_rate
                or wav.getnchannels() != 1
                or wav.getsampwidth() != 2
            ):
                raise AudioError("Cached WAV has wrong sample rate/channels/format")
            frame_count = wav.getnframes()
            if frame_count > _MAX_CACHED_WAV_BYTES // 2:
                raise AudioError("Cached WAV declares excessive audio frames")
            raw_frames = wav.readframes(frame_count)
            # A WAV header may advertise more PCM data than the file actually
            # contains. A matching sidecar checksum alone cannot certify that
            # the declared audio frames were present.
            if len(raw_frames) != frame_count * wav.getnchannels() * wav.getsampwidth():
                raise AudioError("Cached WAV is truncated")
            result = np.frombuffer(raw_frames, dtype="<i2")
            if result.size == 0:
                raise AudioError("Cached WAV is empty")
            return result.astype(np.float32) / 32767.0
    except (wave.Error, EOFError):
        # Untrusted WAV parser diagnostics may include cached payload details.
        raise AudioError("Cached WAV is invalid or unsupported") from None


def _validate_synthesis_inputs(
    provider: TTSProvider, *, speed: float, pause_ms: int, max_retries: int
) -> tuple[int, int]:
    """Validate the arguments and engine metadata before any engine call or cache replay.

    Returns the engine's sample rate and maximum chunk length.
    """
    # Public synthesis is callable without Pydantic or the Kitten adapter.
    # Invalid speed must never reach a third-party engine or cache identity.
    if (
        isinstance(speed, bool)
        or not isinstance(speed, (int, float))
        or not math.isfinite(speed)
        or not 0 < speed <= 3
    ):
        raise AudioError("TTS speech speed must be finite and in (0, 3]")
    # Validate engine metadata before computing pause lengths or replaying
    # persisted WAVs. Invalid rates must never create bogus audio artifacts.
    try:
        rate = getattr(provider, "sample_rate", None)
    except Exception:
        # Third-party engine properties can raise with private model details.
        raise AudioError("Could not inspect TTS provider audio settings") from None
    if isinstance(rate, bool) or not isinstance(rate, int) or not 8000 <= rate <= 192000:
        raise AudioError("TTS provider sample_rate must be an integer from 8000 to 192000")
    if isinstance(pause_ms, bool) or not isinstance(pause_ms, int) or not 0 <= pause_ms <= 5000:
        raise AudioError("TTS pause_ms must be an integer from 0 to 5000")
    if (
        isinstance(max_retries, bool)
        or not isinstance(max_retries, int)
        or not 0 <= max_retries <= 10
    ):
        raise AudioError("TTS max_retries must be an integer from 0 to 10")
    # Legacy mocked providers need no explicit chunk-limit attribute, but
    # concrete providers advertise a hard limit that must be enforced before
    # any synthesis or cache replay. Defaulting to 350 otherwise can send
    # invalid requests to engines with a smaller input window.
    try:
        chunk_limit = getattr(provider, "max_chars_per_chunk", 350)
    except Exception:
        raise AudioError("Could not inspect TTS provider chunk limit") from None
    if isinstance(chunk_limit, bool) or not isinstance(chunk_limit, int) or chunk_limit < 40:
        raise AudioError("TTS provider max_chars_per_chunk must be an integer >= 40")
    return rate, chunk_limit


def _chunk_voices(
    ranges: list[tuple[int, int, bool]], voice: str, voice_changes: list[tuple[int, str]]
) -> list[str]:
    """The voice active at the start of each chunk, following voice markers."""
    chunk_voices: list[str] = []
    change_index = 0
    active_voice = voice
    for start, _end, _boundary in ranges:
        while change_index < len(voice_changes) and voice_changes[change_index][0] <= start:
            active_voice = voice_changes[change_index][1]
            change_index += 1
        chunk_voices.append(active_voice)
    return chunk_voices


def _chunk_plan(
    chapter_text: str,
    voice: str,
    *,
    chunk_limit: int,
    pronunciations: Mapping[str, str] | None,
    skip_citations: bool,
) -> tuple[list[str], list[tuple[int, int]], list[tuple[int, int, bool]], list[str]]:
    """Split the chapter into spoken chunks mapped back to their source text.

    Returns the chunks, the unspeakable pause ranges, each chunk's source
    range and its voice. A chapter with neither chunks nor pauses is refused.
    """
    spoken_source, voice_changes = _voice_markers(chapter_text, voice)
    if skip_citations:
        spoken_source = mask_citations(spoken_source)
    chunks = split_sentences(spoken_source, max_chars=chunk_limit, pronunciations=pronunciations)
    pause_ranges = unspeakable_pause_ranges(chapter_text, skip_citations=skip_citations)
    if not chunks and not pause_ranges:
        raise AudioError("Chapter has no speakable text")
    ranges = chunk_source_ranges(spoken_source, chunks, pronunciations=pronunciations)
    return chunks, pause_ranges, ranges, _chunk_voices(ranges, voice, voice_changes)


def _initial_progress(
    chapter_text: str,
    chunks: list[str],
    ranges: list[tuple[int, int, bool]],
    pause_ranges: list[tuple[int, int]],
    identities: list[str],
    progress_identity: tuple[str, list[str], float, int, int, int],
) -> _SynthesisProgress:
    """Build the chapter's progress ledger with every chunk pending.

    `progress_identity` is (model, chunk voices, speed, rate, pause_ms,
    chunk limit), which with the text and chunk keys fingerprints the run.
    """
    model, chunk_voices, speed, rate, pause_ms, chunk_limit = progress_identity
    chunk_mapping: list[dict[str, int | str]] = []
    for index, (start, end, _boundary) in enumerate(ranges):
        chunk_mapping.append(
            {
                "kind": "speech",
                "number": index + 1,
                "source_start": start,
                "source_end": end,
            }
        )
    for start, end in pause_ranges:
        chunk_mapping.append({"kind": "pause", "source_start": start, "source_end": end})
    # The ledger is diagnostic; it never authorizes reuse without WAV and SHA-256 validation.
    # No source text, voice content, or absolute paths are persisted in the ledger.
    return {
        "schema_version": 1,
        "fingerprint": fingerprint(
            "tts-progress-v4",
            digest_bytes(chapter_text.encode("utf-8")),
            identities,
            model,
            chunk_voices,
            speed,
            rate,
            pause_ms,
            chunk_limit,
        ),
        "total_chunks": len(chunks),
        "pause_count": len(pause_ranges),
        "completed_chunks": 0,
        "status": "in_progress",
        "chunks": [
            {
                "number": index + 1,
                "cache_key": identity,
                "status": "pending",
                "source_start": ranges[index][0],
                "source_end": ranges[index][1],
                "paragraph_boundary_before": ranges[index][2],
                "text_sha256": digest_bytes(chunks[index].encode("utf-8")),
            }
            for index, identity in enumerate(identities)
        ],
        "mapping": sorted(
            chunk_mapping,
            key=lambda item: (item["source_start"], item["source_end"]),
        ),
    }


def _replay_cached_chunk(chunk_path: Path, rate: int) -> tuple[np.ndarray, str, int] | None:
    """Load a cached chunk only if its WAV, checksum and metadata all agree.

    Returns (samples, sha256, byte count), or None for a missing or bad entry;
    a bad cache entry is a miss, never an error.
    """
    checksum_path = chunk_path.with_suffix(".sha256")
    metadata_path = chunk_path.with_suffix(".meta.json")
    if not (chunk_path.is_file() and checksum_path.is_file() and metadata_path.is_file()):
        return None
    try:
        # Check file size before loading untrusted cache bytes into RAM.
        if chunk_path.stat().st_size > _MAX_CACHED_WAV_BYTES:
            raise AudioError("Cached WAV exceeds safe size limit")
        # Bound both reads even if an untrusted cache file changes
        # between stat() and open(). A checksum sidecar needs at most
        # 64 ASCII hex characters plus its trailing newline.
        with chunk_path.open("rb") as cached_stream:
            cached_bytes = cached_stream.read(_MAX_CACHED_WAV_BYTES + 1)
        if len(cached_bytes) > _MAX_CACHED_WAV_BYTES:
            raise AudioError("Cached WAV exceeds safe size limit")
        with checksum_path.open("rb") as checksum_stream:
            saved_digest = checksum_stream.read(66)
        if len(saved_digest) > 65:
            raise AudioError("Cached WAV checksum sidecar is oversized")
        metadata = load_bounded_json(metadata_path, max_bytes=1024, max_depth=4)
        candidate = digest_bytes(cached_bytes)
        if (
            isinstance(metadata, dict)
            and metadata.get("schema_version") == 1
            and metadata.get("sha256") == candidate
            and metadata.get("bytes") == len(cached_bytes)
            and metadata.get("sample_rate") == rate
            and candidate.encode("ascii") == saved_digest.strip()
        ):
            return read_wav(cached_bytes, rate), candidate, len(cached_bytes)
    except (AudioError, OSError, UnicodeError):
        pass
    return None


def _generate_with_retries(
    provider: TTSProvider, text: str, *, voice: str, speed: float, max_retries: int
) -> object:
    """Call the engine, retrying only errors it classifies as transient."""
    audio = None
    for attempt in range(max_retries + 1):
        try:
            audio = provider.generate(text, voice=voice, speed=speed)
            break
        except Exception as exc:
            classifier = getattr(provider, "is_transient_error", None)
            transient = getattr(exc, "transient", False) is True
            if callable(classifier):
                try:
                    transient = classifier(exc) is True
                except Exception:
                    transient = False
            if not transient or attempt >= max_retries:
                # Arbitrary TTS engines can echo book text in their errors.
                raise AudioError("TTS synthesis failed; verify model and voice") from None
            time.sleep(min(0.1 * (2**attempt), 1.0))
    if audio is None:
        raise AudioError("TTS synthesis returned no audio")
    return audio


def _store_generated_chunk(
    audio: object, chunk_path: Path, rate: int
) -> tuple[np.ndarray, str, int]:
    """Canonicalize new audio and write it to the chunk cache.

    Returns (samples, sha256, byte count) exactly as a later replay would read them.
    """
    # Short model chunks must not generate enormous cache entries.
    # Reject oversized ndarray outputs before PCM conversion and
    # also check serialized size for other provider buffer types.
    if isinstance(audio, np.ndarray) and audio.size > (_MAX_CACHED_WAV_BYTES - 44) // 2:
        raise AudioError("TTS chunk exceeds safe WAV cache limit")
    encoded = wav_bytes(cast(np.ndarray, audio), rate)
    if len(encoded) > _MAX_CACHED_WAV_BYTES:
        raise AudioError("TTS chunk exceeds safe WAV cache limit")
    # First-pass PCM must match verified cached PCM exactly:
    # canonicalize clipping and 16-bit quantization before
    # concatenation, not only when replaying the WAV cache.
    samples = read_wav(encoded, rate)
    checksum = digest_bytes(encoded)
    atomic_write(chunk_path, encoded)
    atomic_write(chunk_path.with_suffix(".sha256"), (checksum + "\n").encode())
    write_json(
        chunk_path.with_suffix(".meta.json"),
        {
            "schema_version": 1,
            "sha256": checksum,
            "bytes": len(encoded),
            "sample_rate": rate,
        },
    )
    return samples, checksum, len(encoded)


def _chunk_identities(
    provider: TTSProvider,
    chunks: list[str],
    chunk_voices: list[str],
    model: str,
    speed: float,
    rate: int,
) -> list[str]:
    """The cache key of each chunk: its text, engine, model, voice, speed and rate."""
    # Chunk WAVs are shared across chapters, but never across different
    # synthesis engines even when their model/voice labels and rates coincide.
    # The version marker invalidates older engine-agnostic cache keys.
    engine = f"{type(provider).__module__}.{type(provider).__qualname__}"
    return [
        fingerprint(
            "tts-wav-v3",
            TTS_CHUNK_TEXT_NORMALIZATION_VERSION,
            engine,
            text,
            model,
            chunk_voice,
            speed,
            rate,
        )
        for text, chunk_voice in zip(chunks, chunk_voices, strict=True)
    ]


def _synthesize_new_chunk(
    provider: TTSProvider,
    text: str,
    chunk_path: Path,
    voice: str,
    engine_settings: tuple[float, int, int],
) -> tuple[np.ndarray, str, int]:
    """Synthesize a chunk with retries and store it in the chunk cache.

    `engine_settings` is (speed, sample rate, max retries).
    """
    speed, rate, max_retries = engine_settings
    generated = _generate_with_retries(
        provider, text, voice=voice, speed=speed, max_retries=max_retries
    )
    return _store_generated_chunk(generated, chunk_path, rate)


def _emit_silence(
    writer: _BoundedWavWriter | None, samples: list[np.ndarray], pause: np.ndarray
) -> None:
    """Stream a pause to the chapter WAV, or collect it with the samples."""
    if writer is not None:
        _write_silence(writer, len(pause))
    else:
        samples.append(pause)


def _record_chunk_failure(progress: _SynthesisProgress, progress_stream: Any, idx: int) -> None:
    """Mark a chunk and the chapter failed in the progress ledger."""
    progress["chunks"][idx]["status"] = "failed"
    progress["status"] = "failed"
    _append_progress_update(
        progress_stream,
        number=idx + 1,
        status="failed",
        completed_chunks=progress["completed_chunks"],
    )
    if progress_stream is not None:
        _write_progress_record(progress_stream, {"event": "status", "status": "failed"})
        progress_stream.flush()


def _record_chunk_completion(
    progress: _SynthesisProgress,
    progress_stream: Any,
    idx: int,
    checksum: str,
    size: int,
    report: Callable[[], None] | None,
) -> None:
    """Mark a chunk completed, report it, then append it to the progress stream."""
    progress["chunks"][idx].update(
        {
            "sha256": checksum,
            "bytes": size,
            "status": "completed",
        }
    )
    progress["completed_chunks"] += 1
    if report is not None:
        report()
    _append_progress_update(
        progress_stream,
        number=idx + 1,
        status="completed",
        completed_chunks=progress["completed_chunks"],
        sha256=checksum,
        byte_count=size,
    )


def _finish_progress(progress: _SynthesisProgress, progress_file: Path | None) -> None:
    """Mark the chapter's progress ledger completed."""
    progress["status"] = "completed"
    if progress_file is not None:
        try:
            with progress_file.open("ab") as stream:
                _write_progress_record(stream, {"event": "status", "status": "completed"})
        except OSError:
            raise AudioError("Could not write TTS progress") from None


def synthesize_chunks(
    chapter_text: str,
    provider: TTSProvider,
    *,
    model: str,
    voice: str,
    speed: float,
    pause_ms: int,
    cache: Path,
    use_cache: bool = True,
    progress_file: Path | None = None,
    pronunciations: Mapping[str, str] | None = None,
    max_retries: int = 2,
    output_wav: Path | None = None,
    on_chunk: Callable[[int, bool], None] | None = None,
    skip_citations: bool = False,
) -> np.ndarray | Path:
    """Reuse verified WAV chunks; atomically checkpoint chapter synthesis progress.

    ``on_chunk(characters, cached)`` reports each finished chunk for progress display.
    ``skip_citations`` blanks numeric citations such as ``[13]`` from the spoken text
    (the chapter text and every source offset are unchanged).

    Steps, in order: validation, the chunk plan and cache keys, the progress
    ledger, then per chunk a cache replay or a synthesis with retries,
    streamed or collected, and finally the completed ledger.
    """
    samples: list[np.ndarray] = []
    rate, chunk_limit = _validate_synthesis_inputs(
        provider, speed=speed, pause_ms=pause_ms, max_retries=max_retries
    )
    chunks, pause_ranges, ranges, chunk_voices = _chunk_plan(
        chapter_text,
        voice,
        chunk_limit=chunk_limit,
        pronunciations=pronunciations,
        skip_citations=skip_citations,
    )
    # Use one validated snapshot of the engine rate throughout the request.
    pause = np.zeros(int(rate * pause_ms / 1000), dtype=np.float32)
    paragraph_pause = np.zeros(2 * len(pause), dtype=np.float32)
    identities = _chunk_identities(provider, chunks, chunk_voices, model, speed, rate)
    progress = _initial_progress(
        chapter_text,
        chunks,
        ranges,
        pause_ranges,
        identities,
        (model, chunk_voices, speed, rate, pause_ms, chunk_limit),
    )
    progress_stream = _start_progress_stream(progress_file, progress)
    writer = None
    try:
        writer = _open_streaming_wav(output_wav, rate) if output_wav is not None else None
        if not ranges and pause_ranges:
            for _ in pause_ranges:
                _emit_silence(writer, samples, pause)
        for idx, (text, identity, chunk_voice) in enumerate(
            zip(chunks, identities, chunk_voices, strict=True)
        ):
            chunk_path = cache / f"{identity}.wav"
            replayed = _replay_cached_chunk(chunk_path, rate) if use_cache else None
            cached_chunk = replayed is not None
            if replayed is None:
                try:
                    replayed = _synthesize_new_chunk(
                        provider, text, chunk_path, chunk_voice, (speed, rate, max_retries)
                    )
                except Exception:
                    _record_chunk_failure(progress, progress_stream, idx)
                    raise
            audio, checksum, encoded_size = replayed
            _record_chunk_completion(
                progress,
                progress_stream,
                idx,
                checksum,
                encoded_size,
                None if on_chunk is None else partial(on_chunk, len(text), cached_chunk),
            )
            if idx:
                _emit_silence(writer, samples, paragraph_pause if ranges[idx][2] else pause)
            if writer is not None:
                _write_pcm_chunk(writer, audio)
            else:
                samples.append(audio)
    finally:
        if writer is not None:
            writer.close()
        if progress_stream is not None:
            progress_stream.close()
    _finish_progress(progress, progress_file)
    if writer is not None:
        return cast(Path, output_wav)
    return np.concatenate(samples)


def safe_name(text: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9 _.-]", "_", text)
    return name.strip(" ._")[:90] or "Chapter"


def audio_output_path(manifest: BookManifest, chapter: Chapter, workspace: Path) -> Path:
    return workspace / "audio" / f"{chapter.number:03d} - {safe_name(chapter.title)}.mp3"
