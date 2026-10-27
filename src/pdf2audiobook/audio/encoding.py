"""FFmpeg encoding and audiobook metadata publication."""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
import wave
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Protocol, runtime_checkable

import numpy as np
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4

from pdf2audiobook.errors import AudioError


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
