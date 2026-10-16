"""Audio chunk generation, caching, and single-encode chapter MP3 assembly."""
from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3

from pdf2audiobook.errors import AudioError
from pdf2audiobook.models import BookManifest, Chapter
from pdf2audiobook.tts import TTSProvider
from pdf2audiobook.workspace import atomic_write, digest_bytes, fingerprint


def split_sentences(text: str, max_chars: int = 350) -> list[str]:
    """Split at sentence or word boundaries; preserve full non-whitespace wording."""
    if max_chars < 40:
        raise ValueError("max_chars must be at least 40")
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        words = sentence.split()
        for word in words:
            if len(word) > max_chars:
                raise AudioError("A single narration token exceeds the chunk limit")
            if current and len(current) + len(word) + 1 > max_chars:
                chunks.append(current)
                current = ""
            current = f"{current} {word}".strip()
            if word.endswith((".", "!", "?")):
                # Prefer a clean sentence boundary if enough text has accumulated.
                if len(current) >= max_chars // 2:
                    chunks.append(current)
                    current = ""
    if current:
        chunks.append(current)
    return chunks


def wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    audio = np.asarray(samples, dtype=np.float32).reshape(-1)
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
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            if (
                wav.getframerate() != expected_rate
                or wav.getnchannels() != 1
                or wav.getsampwidth() != 2
            ):
                raise AudioError("Cached WAV has wrong sample rate/channels/format")
            result = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
            if result.size == 0:
                raise AudioError("Cached WAV is empty")
            return result.astype(np.float32) / 32767.0
    except (wave.Error, EOFError) as exc:
        raise AudioError(f"Cached WAV is invalid: {exc}") from exc


def synthesize_chunks(
    chapter_text: str, provider: TTSProvider, *,
    model: str, voice: str, speed: float, pause_ms: int, cache: Path,
    use_cache: bool = True,
) -> np.ndarray:
    """Reuse audio by text/model/voice/speed and concatenate at PCM level."""
    samples: list[np.ndarray] = []
    chunks = split_sentences(chapter_text)
    if not chunks:
        raise AudioError("Chapter has no speakable text")
    pause = np.zeros(int(provider.sample_rate * pause_ms / 1000), dtype=np.float32)
    for idx, text in enumerate(chunks):
        identity = fingerprint(text, model, voice, speed, provider.sample_rate)
        chunk_path = cache / f"{identity}.wav"
        checksum_path = chunk_path.with_suffix(".sha256")
        audio = None
        if use_cache and chunk_path.is_file() and checksum_path.is_file():
            try:
                cached_bytes = chunk_path.read_bytes()
                if digest_bytes(cached_bytes) == checksum_path.read_text().strip():
                    audio = read_wav(cached_bytes, provider.sample_rate)
            except (AudioError, OSError):
                pass
        if audio is None:
            audio = provider.generate(text, voice=voice, speed=speed)
            encoded = wav_bytes(audio, provider.sample_rate)
            atomic_write(chunk_path, encoded)
            atomic_write(checksum_path, (digest_bytes(encoded) + "\n").encode())
        if idx:
            samples.append(pause)
        samples.append(audio)
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
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AudioError(f"FFmpeg failed: {exc}") from exc
        if result.returncode != 0 or not tmp_mp3.is_file():
            raise AudioError(
                f"FFmpeg encoding failed: {result.stderr.decode(errors='replace')[-1000:]}"
            )
        try:
            mp3 = MP3(tmp_mp3, ID3=EasyID3)
            if mp3.tags is None:
                mp3.add_tags()
            mp3.tags["title"] = title
            mp3.tags["album"] = album
            mp3.tags["tracknumber"] = str(track)
            if artist:
                mp3.tags["artist"] = artist
            mp3.save()
            if MP3(tmp_mp3).info.length <= 0:
                raise AudioError("Encoded MP3 has zero duration")
        except AudioError:
            raise
        except Exception as exc:
            raise AudioError(f"MP3 metadata validation failed: {exc}") from exc
        tmp_mp3.replace(output)
    return output


def safe_name(text: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9 _.-]", "_", text)
    return name.strip(" ._")[:90] or "Chapter"


def audio_output_path(manifest: BookManifest, chapter: Chapter, workspace: Path) -> Path:
    return workspace / "audio" / f"{chapter.number:03d} - {safe_name(chapter.title)}.mp3"
