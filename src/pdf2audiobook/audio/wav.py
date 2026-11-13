"""Streaming writer for a chapter's WAV file, bounded by the WAV format's size limit."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from pdf2audiobook.errors import AudioError


class _BoundedWavWriter:
    """Track RIFF payload bytes without depending on wave.Wave_write internals."""

    def __init__(self, writer: wave.Wave_write):
        self.writer = writer
        self.bytes_written = 0

    def writeframesraw(self, frames: bytes) -> None:
        self.writer.writeframesraw(frames)
        self.bytes_written += len(frames)

    def close(self) -> None:
        self.writer.close()


def _open_streaming_wav(path: Path, sample_rate: int) -> _BoundedWavWriter:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        writer = wave.open(str(path), "wb")
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        return _BoundedWavWriter(writer)
    except (OSError, wave.Error):
        raise AudioError("Could not create temporary chapter WAV") from None


def _write_pcm_chunk(writer: _BoundedWavWriter, samples: np.ndarray) -> None:
    try:
        audio = np.asarray(samples, dtype=np.float32)
    except Exception:
        raise AudioError("TTS returned invalid audio sample data") from None
    if audio.ndim != 1 or audio.size == 0 or not np.isfinite(audio).all():
        raise AudioError("TTS returned invalid mono audio samples")
    if writer.bytes_written + audio.size * 2 > 0xFFFFFFFF - 36:
        raise AudioError("Chapter audio exceeds the WAV RIFF size limit")
    for offset in range(0, audio.size, 65536):
        part = audio[offset : offset + 65536]
        pcm = (np.clip(part, -1, 1) * 32767).astype("<i2")
        writer.writeframesraw(pcm.tobytes())


def _write_silence(writer: _BoundedWavWriter, sample_count: int) -> None:
    if writer.bytes_written + sample_count * 2 > 0xFFFFFFFF - 36:
        raise AudioError("Chapter audio exceeds the WAV RIFF size limit")
    block = b"\0" * (65536 * 2)
    remaining = sample_count
    while remaining:
        count = min(remaining, 65536)
        writer.writeframesraw(block[: count * 2])
        remaining -= count
