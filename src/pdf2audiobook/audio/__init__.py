"""Audio chunk generation, caching, and single-encode chapter MP3 assembly."""
from __future__ import annotations

import io
import math
import re
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import NotRequired, TypedDict

import numpy as np
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3

from pdf2audiobook.errors import AudioError
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
    completed_chunks: int
    status: str
    chunks: list[_ChunkProgress]


# Match pairs of logical line endings (CRLF, LF, or CR) with optional
# indentation between them. The same rule controls chunking and source spans.
_PARAGRAPH_BREAK = re.compile(r"(?>\r\n|\r|\n)[ \t]*(?>\r\n|\r|\n)+")


# Short TTS chunks must never require a 128 MiB WAV cache entry.
_MAX_CACHED_WAV_BYTES = 128 * 1024 * 1024


def split_sentences(text: str, max_chars: int = 350) -> list[str]:
    """Split at sentence/word boundaries without crossing source paragraphs."""
    if max_chars < 40:
        raise ValueError("max_chars must be at least 40")
    chunks: list[str] = []
    # Blank lines are semantic paragraph boundaries, including PDF-derived
    # CR-only line endings; a single soft wrap is not a paragraph break.
    for paragraph in _PARAGRAPH_BREAK.split(text.strip()):
        current = ""
        for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
            for word in sentence.split():
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
    chapter_text: str, chunks: list[str],
) -> list[tuple[int, int, bool]]:
    """Map normalized spoken chunks to exact source character ranges, in order."""
    words = list(re.finditer(r"\S+", chapter_text))
    positions: list[tuple[int, int, bool]] = []
    cursor = 0
    previous_end = 0
    for chunk in chunks:
        parts = chunk.split()
        group = words[cursor:cursor + len(parts)]
        if not group or [match.group() for match in group] != parts:
            raise AudioError("Narration chunk source alignment failed")
        start, end = group[0].start(), group[-1].end()
        paragraph_boundary = bool(
            _PARAGRAPH_BREAK.search(chapter_text[previous_end:start])
        )
        positions.append((start, end, paragraph_boundary))
        previous_end = end
        cursor += len(parts)
    if cursor != len(words):
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
    chapter_text: str, provider: TTSProvider, *,
    model: str, voice: str, speed: float, pause_ms: int, cache: Path,
    use_cache: bool = True, progress_file: Path | None = None,
) -> np.ndarray:
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
    chunks = split_sentences(chapter_text, max_chars=chunk_limit)
    if not chunks:
        raise AudioError("Chapter has no speakable text")
    # Use one validated snapshot of the engine rate throughout the request.
    pause = np.zeros(int(rate * pause_ms / 1000), dtype=np.float32)
    paragraph_pause = np.zeros(2 * len(pause), dtype=np.float32)
    ranges = chunk_source_ranges(chapter_text, chunks)
    # Chunk WAVs are shared across chapters, but never across different
    # synthesis engines even when their model/voice labels and rates coincide.
    # The version marker invalidates older engine-agnostic cache keys.
    engine = f"{type(provider).__module__}.{type(provider).__qualname__}"
    identities = [
        fingerprint("tts-wav-v2", engine, text, model, voice, speed, rate)
        for text in chunks
    ]
    # The ledger is diagnostic; it never authorizes reuse without WAV and SHA-256 validation.
    # No source text, voice content, or absolute paths are persisted in the ledger.
    progress: _SynthesisProgress = {
        "schema_version": 1,
        "fingerprint": fingerprint(
            "tts-progress-v3", digest_bytes(chapter_text.encode("utf-8")), identities,
            model, voice, speed, rate,
            pause_ms, chunk_limit,
        ),
        "total_chunks": len(chunks),
        "completed_chunks": 0,
        "status": "in_progress",
        "chunks": [
            {
                "number": index + 1, "cache_key": identity, "status": "pending",
                "source_start": ranges[index][0], "source_end": ranges[index][1],
                "paragraph_boundary_before": ranges[index][2],
                "text_sha256": digest_bytes(chunks[index].encode("utf-8")),
            }
            for index, identity in enumerate(identities)
        ],
    }
    if progress_file is not None:
        write_json(progress_file, progress)
    for idx, (text, identity) in enumerate(zip(chunks, identities, strict=True)):
        chunk_path = cache / f"{identity}.wav"
        checksum_path = chunk_path.with_suffix(".sha256")
        audio = None
        checksum = None
        encoded_size = None
        if use_cache and chunk_path.is_file() and checksum_path.is_file():
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
                candidate = digest_bytes(cached_bytes)
                if candidate.encode("ascii") == saved_digest.strip():
                    audio = read_wav(cached_bytes, rate)
                    checksum = candidate
                    encoded_size = len(cached_bytes)
            except (AudioError, OSError, UnicodeError):
                pass
        if audio is None:
            try:
                try:
                    audio = provider.generate(text, voice=voice, speed=speed)
                except Exception:
                    # Arbitrary TTS engines can echo book text in their errors.
                    raise AudioError("TTS synthesis failed; verify model and voice") from None
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
                encoded_size = len(encoded)
            except Exception:
                progress["chunks"][idx]["status"] = "failed"
                progress["status"] = "failed"
                if progress_file is not None:
                    write_json(progress_file, progress)
                raise
        progress["chunks"][idx].update({
            "sha256": checksum, "bytes": encoded_size, "status": "completed",
        })
        progress["completed_chunks"] += 1
        if progress_file is not None:
            write_json(progress_file, progress)
        if idx:
            samples.append(paragraph_pause if ranges[idx][2] else pause)
        samples.append(audio)
    progress["status"] = "completed"
    if progress_file is not None:
        write_json(progress_file, progress)
    return np.concatenate(samples)


def encode_mp3(
    samples: np.ndarray, sample_rate: int, output: Path, *,
    bitrate: str, target_rate: int, title: str, artist: str | None,
    album: str, track: int,
) -> Path:
    """Encode once from PCM to MP3, tag and atomically publish final file."""
    if shutil.which("ffmpeg") is None:
        raise AudioError("FFmpeg executable not found in PATH")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temp_dir:
        wav_path = Path(temp_dir) / "chapter.wav"
        tmp_mp3 = Path(temp_dir) / "chapter.mp3"
        wav_path.write_bytes(wav_bytes(samples, sample_rate))
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(wav_path), "-ar", str(target_rate), "-ac", "1",
            "-b:a", bitrate, str(tmp_mp3)
        ]
        try:
            result = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                check=False, timeout=1800
            )
        except subprocess.TimeoutExpired:
            # Third-party exception text can expose output paths or PDF-derived data.
            raise AudioError("FFmpeg encoding timed out; check the audio and system resources") from None
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
            info = MP3(tmp_mp3).info
            if info is None or info.length <= 0:
                raise AudioError("Encoded MP3 has zero duration")
        except AudioError:
            raise
        except Exception:
            # Parser diagnostics can echo source-derived ID3 values or paths.
            raise AudioError("MP3 metadata validation failed; check encoded audio") from None
        tmp_mp3.replace(output)
    return output


def safe_name(text: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9 _.-]", "_", text)
    return name.strip(" ._")[:90] or "Chapter"


def audio_output_path(manifest: BookManifest, chapter: Chapter, workspace: Path) -> Path:
    return workspace / "audio" / f"{chapter.number:03d} - {safe_name(chapter.title)}.mp3"
