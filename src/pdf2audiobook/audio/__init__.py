"""Audio chunk generation, caching, and single-encode chapter MP3 assembly."""

from __future__ import annotations

import io
import math
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
import wave
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping, NotRequired, Protocol, TypedDict, runtime_checkable

import numpy as np
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4

from pdf2audiobook.errors import AudioError, ConfigError
from pdf2audiobook.jsonio import load_bounded_json
from pdf2audiobook.models import BookManifest, Chapter
from pdf2audiobook.tts import TTSProvider
from pdf2audiobook.workspace import atomic_write, digest_bytes, fingerprint, write_json


class _ChunkProgress(TypedDict):
    number: int
    cache_key: str
    status: str
    source_start: int
    source_end: int
    paragraph_boundary_before: bool
    text_sha256: str
    sha256: NotRequired[str | None]
    bytes: NotRequired[int | None]


class _SynthesisProgress(TypedDict):
    schema_version: int
    fingerprint: str
    total_chunks: int
    pause_count: int
    completed_chunks: int
    status: str
    chunks: list[_ChunkProgress]
    mapping: list[dict[str, int | str]]


def _open_streaming_wav(path: Path, sample_rate: int) -> wave.Wave_write:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        writer = wave.open(str(path), "wb")
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        return writer
    except (OSError, wave.Error):
        raise AudioError("Could not create temporary chapter WAV") from None


def _write_pcm_chunk(writer: wave.Wave_write, samples: np.ndarray) -> None:
    try:
        audio = np.asarray(samples, dtype=np.float32)
    except Exception:
        raise AudioError("TTS returned invalid audio sample data") from None
    if audio.ndim != 1 or audio.size == 0 or not np.isfinite(audio).all():
        raise AudioError("TTS returned invalid mono audio samples")
    if getattr(writer, "_datawritten", 0) + audio.size * 2 > 0xFFFFFFFF - 36:
        raise AudioError("Chapter audio exceeds the WAV RIFF size limit")
    for offset in range(0, audio.size, 65536):
        part = audio[offset : offset + 65536]
        pcm = (np.clip(part, -1, 1) * 32767).astype("<i2")
        writer.writeframesraw(pcm.tobytes())


def _write_silence(writer: wave.Wave_write, sample_count: int) -> None:
    if getattr(writer, "_datawritten", 0) + sample_count * 2 > 0xFFFFFFFF - 36:
        raise AudioError("Chapter audio exceeds the WAV RIFF size limit")
    block = b"\0" * (65536 * 2)
    remaining = sample_count
    while remaining:
        count = min(remaining, 65536)
        writer.writeframesraw(block[: count * 2])
        remaining -= count


# Match pairs of logical line endings (CRLF, LF, or CR) with optional
# indentation between them. The same rule controls chunking and source spans.
_PARAGRAPH_BREAK = re.compile(r"(?>\r\n|\r|\n)[ \t]*(?>\r\n|\r|\n)+")
_VOICE_MARKER = re.compile(
    r"(?m)^\[\[voice:([A-Za-z0-9][A-Za-z0-9_.-]{0,127})\]\][ \t]*(?:\r?\n|$)"
)
NARRATION_NORMALIZATION_VERSION = "narration-normalization-v1"
_NARRATION_TRANSLATION = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "…": "...",
        "ﬁ": "fi",
        "ﬂ": "fl",
        "ﬀ": "ff",
        "ﬃ": "ffi",
        "ﬄ": "ffl",
        "ﬅ": "st",
        "ﬆ": "st",
        "\u00a0": " ",
        "\u00ad": "",
        "\u200b": "",
        "\u200c": "",
        "\u200d": "",
        "\u2060": "",
        "\ufeff": "",
    }
)
_SCENE_BREAK = re.compile(r"^\s*(?:\*\s*){3,}$")
_PRONUNCIATION_EDGE = {'"', "'", "(", ")", "[", "]", "{", "}", "<", ">"}
_PRONUNCIATION_TRAILING = {",", ";", ":", "!", "?", "…"}


_DASHES = "–—―"
_DASH_RUN = re.compile(rf"\s*[{_DASHES}]+\s*")


def normalize_narration_text(text: str) -> str:
    """Apply the documented TTS-only character table without changing source data."""
    text = re.sub(r"(?<=\d)–(?=\d)", " to ", text)
    text = _DASH_RUN.sub(", ", text)
    return text.translate(_NARRATION_TRANSLATION)


_INVISIBLE = re.compile("[\u00ad\u200b\u200c\u200d\u2060\ufeff]")


def _droppable_word(word: str) -> bool:
    """Source words that legitimately produce no spoken token of their own."""
    return not _INVISIBLE.sub("", word).strip(_DASHES)


def _spoken_sequence(words: list[str], pronunciations: Mapping[str, str] | None) -> list[str]:
    """Spoken text for each source word of one paragraph.

    A word may speak as several tokens ("10–20" becomes "10 to 20") or as none
    (a bare dash only moves a comma onto the previous spoken word), so callers
    align on source words, never on token counts.
    """
    spoken: list[str] = []

    def attach_comma() -> None:
        for index in range(len(spoken) - 1, -1, -1):
            if spoken[index]:
                if not spoken[index].endswith((",", ";", ":", ".", "!", "?")):
                    spoken[index] += ","
                return

    for word in words:
        core = word.strip(_DASHES)
        if not core:
            attach_comma()
            spoken.append("")
            continue
        if word[0] in _DASHES:
            attach_comma()
        text = _spoken_token(core, pronunciations)
        if word[-1] in _DASHES and text and not text.endswith((",", ";", ":", ".", "!", "?")):
            text += ","
        spoken.append(text)
    return spoken


def _unspeakable_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    cursor = 0
    for match in _PARAGRAPH_BREAK.finditer(text):
        if not has_speakable_narration(text[cursor : match.start()]):
            ranges.append((cursor, match.start()))
        cursor = match.end()
    if not has_speakable_narration(text[cursor:]):
        ranges.append((cursor, len(text)))
    return ranges


def has_speakable_narration(text: str) -> bool:
    """Return false for whitespace and decorative scene-break-only text."""
    return any(
        paragraph.strip()
        and not _SCENE_BREAK.fullmatch(paragraph)
        and any(char.isalnum() for char in paragraph)
        for paragraph in _PARAGRAPH_BREAK.split(text)
    )


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


def _spoken_token(token: str, pronunciations: Mapping[str, str] | None = None) -> str:
    normalized = normalize_narration_text(token)
    if not pronunciations:
        return normalized
    start = 0
    end = len(normalized)
    while start < end and (
        normalized[start] in _PRONUNCIATION_EDGE
        or unicodedata.category(normalized[start]).startswith("Ps")
    ):
        start += 1
    while end > start and (
        normalized[end - 1] in _PRONUNCIATION_EDGE
        or normalized[end - 1] in _PRONUNCIATION_TRAILING
        or unicodedata.category(normalized[end - 1]).startswith("Pe")
    ):
        end -= 1
    core = normalized[start:end]
    has_terminal_period = core.endswith(".") and not normalized[end:].startswith(",")
    pronunciation_core = (core[:-1] if has_terminal_period else core).rstrip(".")
    spoken = pronunciations.get(core.casefold())
    if spoken is None:
        spoken = pronunciations.get(pronunciation_core.casefold())
    if spoken is None:
        return normalized
    if pronunciation_core.isalpha() and pronunciation_core.isupper():
        spoken = spoken.upper()
    elif pronunciation_core.isalpha() and pronunciation_core.istitle():
        spoken = spoken.capitalize()
    period = "." if has_terminal_period else ""
    return f"{normalized[:start]}{spoken}{period}{normalized[end:]}"


def _voice_markers(text: str, default_voice: str) -> tuple[str, list[tuple[int, str]]]:
    """Mask paragraph-level ``[[voice:ID]]`` markers and return source offsets."""
    changes: list[tuple[int, str]] = []
    masked = list(text)
    for match in _VOICE_MARKER.finditer(text):
        start, end = match.span()
        before = text[:start]
        after = text[end:]
        if before.strip() and not _PARAGRAPH_BREAK.search(before[-16:]):
            raise AudioError("Speaker markers must start a new paragraph")
        if after.strip() and not after.startswith(("\n", "\r")):
            raise AudioError("Speaker markers must end before a blank line")
        # Keep newlines and character offsets intact for source-range records.
        for index in range(start, end):
            if masked[index] not in "\r\n":
                masked[index] = " "
        changes.append((end, match.group(1)))
    voices = [(0, default_voice), *changes]
    return "".join(masked), voices


def voice_marker_ids(text: str) -> list[str]:
    """Validate marker placement and return explicit voice IDs in source order."""
    return [voice for _, voice in _voice_markers(text, "")[1][1:]]


def split_sentences(
    text: str,
    max_chars: int = 350,
    pronunciations: Mapping[str, str] | None = None,
) -> list[str]:
    """Split at sentence/word boundaries without crossing source paragraphs."""
    if max_chars < 40:
        raise ValueError("max_chars must be at least 40")
    chunks: list[str] = []
    # Blank lines are semantic paragraph boundaries, including PDF-derived
    # CR-only line endings; a single soft wrap is not a paragraph break.
    for paragraph in _PARAGRAPH_BREAK.split(text.strip()):
        if not has_speakable_narration(paragraph):
            continue
        current = ""
        for word in _spoken_sequence(paragraph.split(), pronunciations):
            if len(word) > max_chars:
                raise AudioError("A single narration token exceeds the chunk limit")
            if current and len(current) + len(word) + 1 > max_chars:
                chunks.append(current)
                current = ""
            current = f"{current} {word}".strip()
            if word.endswith((".", "!", "?")) and len(current) >= max_chars // 2:
                chunks.append(current)
                current = ""
        if current:
            chunks.append(current)
    return chunks


def chunk_source_ranges(
    chapter_text: str,
    chunks: list[str],
    pronunciations: Mapping[str, str] | None = None,
) -> list[tuple[int, int, bool]]:
    """Map normalized spoken chunks to exact source character ranges, in order."""
    scene_ranges = _unspeakable_ranges(chapter_text)
    words = [
        match
        for match in re.finditer(r"\S+", chapter_text)
        if not any(start <= match.start() and match.end() <= end for start, end in scene_ranges)
    ]
    spoken: list[list[str]] = []
    group: list[re.Match[str]] = []
    for match in words:
        if group and _PARAGRAPH_BREAK.search(chapter_text[group[-1].end() : match.start()]):
            spoken.extend(
                part.split()
                for part in _spoken_sequence([item.group() for item in group], pronunciations)
            )
            group = []
        group.append(match)
    if group:
        spoken.extend(
            part.split()
            for part in _spoken_sequence([item.group() for item in group], pronunciations)
        )
    positions: list[tuple[int, int, bool]] = []
    cursor = 0
    previous_end = 0
    failure = "Narration chunk source alignment failed"
    for chunk in chunks:
        parts = chunk.split()
        if not parts:
            raise AudioError(failure)
        while cursor < len(words) and not spoken[cursor] and _droppable_word(words[cursor].group()):
            cursor += 1
        first = last = cursor
        index = 0
        while index < len(parts):
            if cursor >= len(words):
                raise AudioError(failure)
            tokens = spoken[cursor]
            if not tokens:
                if not _droppable_word(words[cursor].group()):
                    raise AudioError(failure)
            elif parts[index : index + len(tokens)] != tokens:
                raise AudioError(failure)
            else:
                index += len(tokens)
                last = cursor
            cursor += 1
        while (
            cursor < len(words)
            and not spoken[cursor]
            and _droppable_word(words[cursor].group())
            and not _PARAGRAPH_BREAK.search(chapter_text[words[last].end() : words[cursor].start()])
        ):
            last = cursor
            cursor += 1
        start, end = words[first].start(), words[last].end()
        paragraph_boundary = bool(_PARAGRAPH_BREAK.search(chapter_text[previous_end:start]))
        positions.append((start, end, paragraph_boundary))
        previous_end = end
    if any(
        spoken[rest] or not _droppable_word(words[rest].group())
        for rest in range(cursor, len(words))
    ):
        raise AudioError("Narration chunks do not cover all source words")
    return positions


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
) -> np.ndarray | Path:
    """Reuse verified WAV chunks; atomically checkpoint chapter synthesis progress."""
    samples: list[np.ndarray] = []
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
    spoken_source, voice_changes = _voice_markers(chapter_text, voice)
    chunks = split_sentences(spoken_source, max_chars=chunk_limit, pronunciations=pronunciations)
    if not chunks:
        raise AudioError("Chapter has no speakable text")
    # Use one validated snapshot of the engine rate throughout the request.
    pause = np.zeros(int(rate * pause_ms / 1000), dtype=np.float32)
    paragraph_pause = np.zeros(2 * len(pause), dtype=np.float32)
    ranges = chunk_source_ranges(spoken_source, chunks, pronunciations=pronunciations)
    pause_ranges = [
        (start, end)
        for start, end in _unspeakable_ranges(spoken_source)
        if _SCENE_BREAK.fullmatch(spoken_source[start:end].strip())
    ]
    chunk_voices: list[str] = []
    change_index = 0
    active_voice = voice
    for start, _end, _boundary in ranges:
        while change_index < len(voice_changes) and voice_changes[change_index][0] <= start:
            active_voice = voice_changes[change_index][1]
            change_index += 1
        chunk_voices.append(active_voice)
    # Chunk WAVs are shared across chapters, but never across different
    # synthesis engines even when their model/voice labels and rates coincide.
    # The version marker invalidates older engine-agnostic cache keys.
    engine = f"{type(provider).__module__}.{type(provider).__qualname__}"
    identities = [
        fingerprint(
            "tts-wav-v3",
            NARRATION_NORMALIZATION_VERSION,
            engine,
            text,
            model,
            chunk_voice,
            speed,
            rate,
        )
        for text, chunk_voice in zip(chunks, chunk_voices, strict=True)
    ]
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
    progress: _SynthesisProgress = {
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
    if progress_file is not None:
        write_json(progress_file, progress)
    writer = _open_streaming_wav(output_wav, rate) if output_wav is not None else None
    try:
        for idx, (text, identity, chunk_voice) in enumerate(
            zip(chunks, identities, chunk_voices, strict=True)
        ):
            chunk_path = cache / f"{identity}.wav"
            checksum_path = chunk_path.with_suffix(".sha256")
            metadata_path = chunk_path.with_suffix(".meta.json")
            audio = None
            checksum = None
            encoded_size = None
            if (
                use_cache
                and chunk_path.is_file()
                and checksum_path.is_file()
                and metadata_path.is_file()
            ):
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
                        audio = read_wav(cached_bytes, rate)
                        checksum = candidate
                        encoded_size = len(cached_bytes)
                except (AudioError, OSError, UnicodeError):
                    pass
            if audio is None:
                try:
                    for attempt in range(max_retries + 1):
                        try:
                            audio = provider.generate(text, voice=chunk_voice, speed=speed)
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
                                raise AudioError(
                                    "TTS synthesis failed; verify model and voice"
                                ) from None
                            time.sleep(min(0.1 * (2**attempt), 1.0))
                    if audio is None:
                        raise AudioError("TTS synthesis returned no audio")
                    # Short model chunks must not generate enormous cache entries.
                    # Reject oversized ndarray outputs before PCM conversion and
                    # also check serialized size for other provider buffer types.
                    if (
                        isinstance(audio, np.ndarray)
                        and audio.size > (_MAX_CACHED_WAV_BYTES - 44) // 2
                    ):
                        raise AudioError("TTS chunk exceeds safe WAV cache limit")
                    encoded = wav_bytes(audio, rate)
                    if len(encoded) > _MAX_CACHED_WAV_BYTES:
                        raise AudioError("TTS chunk exceeds safe WAV cache limit")
                    # First-pass PCM must match verified cached PCM exactly:
                    # canonicalize clipping and 16-bit quantization before
                    # concatenation, not only when replaying the WAV cache.
                    audio = read_wav(encoded, rate)
                    checksum = digest_bytes(encoded)
                    atomic_write(chunk_path, encoded)
                    atomic_write(checksum_path, (checksum + "\n").encode())
                    write_json(
                        metadata_path,
                        {
                            "schema_version": 1,
                            "sha256": checksum,
                            "bytes": len(encoded),
                            "sample_rate": rate,
                        },
                    )
                    encoded_size = len(encoded)
                except Exception:
                    progress["chunks"][idx]["status"] = "failed"
                    progress["status"] = "failed"
                    if progress_file is not None:
                        write_json(progress_file, progress)
                    raise
            progress["chunks"][idx].update(
                {
                    "sha256": checksum,
                    "bytes": encoded_size,
                    "status": "completed",
                }
            )
            progress["completed_chunks"] += 1
            if progress_file is not None:
                write_json(progress_file, progress)
            if idx:
                if writer is not None:
                    _write_silence(writer, len(paragraph_pause if ranges[idx][2] else pause))
                else:
                    samples.append(paragraph_pause if ranges[idx][2] else pause)
            if writer is not None:
                _write_pcm_chunk(writer, audio)
            else:
                samples.append(audio)
    finally:
        if writer is not None:
            writer.close()
    progress["status"] = "completed"
    if progress_file is not None:
        write_json(progress_file, progress)
    if writer is not None:
        if output_wav is None:
            raise AudioError("Temporary chapter WAV path is missing")
        return output_wav
    return np.concatenate(samples)


def _write_chapter_wav(samples: np.ndarray, sample_rate: int, target: Path) -> None:
    """Stream full-chapter PCM to WAV without applying the short-chunk cache cap.

    Chapter audio may legitimately exceed 128 MiB. A fixed-size conversion
    buffer prevents a second chapter-sized PCM allocation during encoding.
    """
    if (
        isinstance(sample_rate, bool)
        or not isinstance(sample_rate, int)
        or not 8000 <= sample_rate <= 192000
    ):
        raise AudioError("Audio sample_rate must be an integer from 8000 to 192000")
    try:
        audio = np.asarray(samples, dtype=np.float32)
    except Exception:
        raise AudioError("TTS returned invalid audio sample data") from None
    if audio.ndim != 1:
        raise AudioError("TTS audio must be a one-dimensional mono sample buffer")
    if audio.size == 0:
        raise AudioError("TTS returned empty/nonfinite audio samples")
    if audio.size > (0xFFFFFFFF - 36) // 2:
        raise AudioError("Chapter audio exceeds the WAV RIFF size limit")
    try:
        with wave.open(str(target), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(sample_rate)
            for offset in range(0, audio.size, 65536):
                part = audio[offset : offset + 65536]
                if not np.isfinite(part).all():
                    raise AudioError("TTS returned empty/nonfinite audio samples")
                pcm = (np.clip(part, -1, 1) * 32767).astype("<i2")
                out.writeframesraw(pcm.tobytes())
    except (OSError, wave.Error):
        raise AudioError("Could not write chapter PCM WAV") from None


def _validate_chapter_wav(path: Path, sample_rate: int) -> None:
    """Validate streamed PCM WAV in bounded memory before passing it to FFmpeg."""
    try:
        with wave.open(str(path), "rb") as source:
            if (
                source.getnchannels() != 1
                or source.getsampwidth() != 2
                or source.getframerate() != sample_rate
                or source.getnframes() <= 0
            ):
                raise AudioError("Temporary chapter WAV has invalid audio settings")
            while source.readframes(65536):
                pass
    except AudioError:
        raise
    except (OSError, wave.Error, EOFError):
        raise AudioError("Temporary chapter WAV is invalid or truncated") from None


@contextmanager
def _safe_chapter_workspace(parent: Path) -> Iterator[str]:
    """Convert temporary directory creation and cleanup OS errors to safe diagnostics."""
    try:
        with tempfile.TemporaryDirectory(dir=parent) as temp_dir:
            yield temp_dir
    except OSError:
        # Temporary-directory errors may embed book titles or private paths.
        raise AudioError("Could not manage temporary MP3 workspace; check permissions") from None


@runtime_checkable
class AudioEncoder(Protocol):
    """Replaceable chapter encoder: one PCM chapter in, one tagged file out."""

    def __call__(
        self,
        samples: np.ndarray | Path,
        sample_rate: int,
        output: Path,
        *,
        bitrate: str,
        target_rate: int,
        title: str,
        artist: str | None,
        album: str,
        track: int,
        cover_image: tuple[bytes, str] | None = None,
    ) -> Path:
        """Encode once, tag and atomically publish output; return its path."""


def encode_mp3(
    samples: np.ndarray | Path,
    sample_rate: int,
    output: Path,
    *,
    bitrate: str,
    target_rate: int,
    title: str,
    artist: str | None,
    album: str,
    track: int,
    cover_image: tuple[bytes, str] | None = None,
) -> Path:
    """Encode once from PCM to MP3, tag and atomically publish final file."""
    if shutil.which("ffmpeg") is None:
        raise AudioError("FFmpeg executable not found in PATH")
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise AudioError("Could not create MP3 output directory; check permissions") from None
    with _safe_chapter_workspace(output.parent) as temp_dir:
        wav_path = Path(temp_dir) / "chapter.wav"
        tmp_mp3 = Path(temp_dir) / "chapter.mp3"
        if isinstance(samples, Path):
            _validate_chapter_wav(samples, sample_rate)
            wav_path = samples
        else:
            _write_chapter_wav(samples, sample_rate, wav_path)
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(wav_path),
            "-ar",
            str(target_rate),
            "-ac",
            "1",
            "-b:a",
            bitrate,
            str(tmp_mp3),
        ]
        try:
            result = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=1800
            )
        except subprocess.TimeoutExpired:
            # Third-party exception text can expose output paths or PDF-derived data.
            raise AudioError(
                "FFmpeg encoding timed out; check the audio and system resources"
            ) from None
        except OSError:
            raise AudioError("Cannot execute FFmpeg; check installation and permissions") from None
        if result.returncode != 0 or not tmp_mp3.is_file():
            # FFmpeg stderr may include private workspace paths or metadata.
            raise AudioError(
                f"FFmpeg encoding failed (exit status {result.returncode}); "
                "check codec support and audio settings"
            )
        try:
            mp3 = MP3(tmp_mp3, ID3=EasyID3)
            tags = mp3.tags
            if tags is None:
                mp3.add_tags()
                tags = mp3.tags
            if tags is None:
                raise AudioError("Could not initialize MP3 metadata tags")
            tags["title"] = title
            tags["album"] = album
            tags["tracknumber"] = str(track)
            if artist:
                tags["artist"] = artist
            mp3.save()
            if cover_image is not None:
                from mutagen.id3 import APIC, ID3

                cover_bytes, mime = cover_image
                id3_tags = ID3(tmp_mp3)
                id3_tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=cover_bytes))
                id3_tags.save(tmp_mp3)
            info = MP3(tmp_mp3).info
            if info is None or info.length <= 0:
                raise AudioError("Encoded MP3 has zero duration")
        except AudioError:
            raise
        except Exception:
            # Parser diagnostics can echo source-derived ID3 values or paths.
            raise AudioError("MP3 metadata validation failed; check encoded audio") from None
        try:
            tmp_mp3.replace(output)
        except OSError:
            # The OS error may reveal a private output directory or book title.
            raise AudioError("Could not publish encoded MP3; check output permissions") from None
    return output


def _ffmetadata_value(value: str) -> str:
    """Escape a metadata value for FFmpeg's text metadata format."""
    return (
        value.replace("\\", "\\\\")
        .replace("=", "\\=")
        .replace(";", "\\;")
        .replace("#", "\\#")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def encode_m4b(
    chapters: list[tuple[Path, str]],
    output: Path,
    *,
    title: str,
    artist: str | None,
    bitrate: str = "96k",
    cover_image: tuple[bytes, str] | None = None,
) -> Path:
    """Package existing chapter MP3s as a tagged AAC audiobook with chapter marks."""
    if shutil.which("ffmpeg") is None:
        raise AudioError("FFmpeg executable not found in PATH")
    if not chapters:
        raise AudioError("Cannot package an audiobook with no chapters")
    durations: list[float] = []
    for path, _ in chapters:
        try:
            info = MP3(path).info
            duration_seconds = float(info.length) if info is not None else 0.0
            if not path.is_file() or not math.isfinite(duration_seconds) or duration_seconds <= 0:
                raise ValueError("invalid duration")
            durations.append(duration_seconds)
        except Exception:
            raise AudioError(
                "An audiobook chapter is missing, invalid or has zero duration"
            ) from None
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise AudioError("Could not create audiobook output directory; check permissions") from None
    with _safe_chapter_workspace(output.parent) as temp_dir:
        workspace = Path(temp_dir)
        concat_path = workspace / "chapters.txt"
        metadata_path = workspace / "metadata.txt"
        temp_output = workspace / "book.m4b"
        concat_lines = []
        metadata_lines = [";FFMETADATA1", f"title={_ffmetadata_value(title)}"]
        if artist:
            metadata_lines.append(f"artist={_ffmetadata_value(artist)}")
        metadata_lines.append(f"album={_ffmetadata_value(title)}")
        cursor_ms = 0
        for index, ((chapter_path, chapter_title), duration) in enumerate(
            zip(chapters, durations, strict=True), start=1
        ):
            staged = workspace / f"chapter-{index:05d}.mp3"
            try:
                staged.symlink_to(chapter_path.resolve())
            except OSError:
                try:
                    shutil.copyfile(chapter_path, staged)
                except OSError:
                    raise AudioError("Could not stage audiobook chapter audio") from None
            concat_lines.append(f"file '{staged.name}'")
            end_ms = cursor_ms + max(1, round(duration * 1000))
            metadata_lines.extend(
                (
                    "[CHAPTER]",
                    "TIMEBASE=1/1000",
                    f"START={cursor_ms}",
                    f"END={end_ms}",
                    f"title={_ffmetadata_value(chapter_title)}",
                )
            )
            cursor_ms = end_ms
        concat_path.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
        metadata_path.write_text("\n".join(metadata_lines) + "\n", encoding="utf-8")
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-f",
            "ffmetadata",
            "-i",
            str(metadata_path),
            "-map",
            "0:a:0",
            "-map_metadata",
            "1",
            "-map_chapters",
            "1",
            "-c:a",
            "aac",
            "-b:a",
            bitrate,
            "-movflags",
            "+faststart",
            str(temp_output),
        ]
        try:
            result = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=3600
            )
        except (subprocess.TimeoutExpired, OSError):
            raise AudioError("FFmpeg audiobook packaging failed or timed out") from None
        if result.returncode != 0 or not temp_output.is_file() or temp_output.stat().st_size == 0:
            raise AudioError(f"FFmpeg audiobook packaging failed (exit status {result.returncode})")
        try:
            container = MP4(temp_output)
            if container.info is None or container.info.length <= 0:
                raise ValueError("empty MP4 audio")
            if container.tags is None:
                container.add_tags()
            container.tags["\xa9nam"] = title
            container.tags["\xa9alb"] = title
            if artist:
                container.tags["\xa9ART"] = artist
            if cover_image is not None:
                from mutagen.mp4 import MP4Cover

                cover_bytes, mime = cover_image
                image_format = MP4Cover.FORMAT_JPEG if mime == "image/jpeg" else MP4Cover.FORMAT_PNG
                container.tags["covr"] = [MP4Cover(cover_bytes, imageformat=image_format)]
            container.save()
            # Reparse after tagging before publication.
            if MP4(temp_output).info is None:
                raise ValueError("invalid MP4 audio")
        except Exception:
            raise AudioError("M4B metadata validation failed; check encoded audio") from None
        try:
            temp_output.replace(output)
        except OSError:
            raise AudioError("Could not publish M4B audiobook; check output permissions") from None
    return output


def safe_name(text: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9 _.-]", "_", text)
    return name.strip(" ._")[:90] or "Chapter"


def audio_output_path(manifest: BookManifest, chapter: Chapter, workspace: Path) -> Path:
    return workspace / "audio" / f"{chapter.number:03d} - {safe_name(chapter.title)}.mp3"
