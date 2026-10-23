"""Reject checksum-matching WAV cache entries whose PCM payload is incomplete."""

from pathlib import Path

import numpy as np
import pytest

from pdf2audiobook.audio import read_wav, synthesize_chunks, wav_bytes
from pdf2audiobook.errors import AudioError
from pdf2audiobook.workspace import digest_bytes, fingerprint


class _SyntheticTTS:
    sample_rate = 24000
    max_chars_per_chunk = 350

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, text: str, *, voice: str, speed: float) -> np.ndarray:
        self.calls += 1
        return np.full(500, 0.25, dtype=np.float32)


def test_wav_with_declared_but_missing_pcm_frames_is_rejected() -> None:
    complete = wav_bytes(np.zeros(500, dtype=np.float32), 24000)
    truncated = complete[:-40]
    with pytest.raises(AudioError, match="Cached WAV is truncated"):
        read_wav(truncated, 24000)


def test_truncated_wav_with_matching_checksum_is_regenerated(tmp_path: Path) -> None:
    text = "A complete synthetic sentence."
    provider = _SyntheticTTS()
    cache = tmp_path / "cache"
    cache.mkdir()
    engine = f"{type(provider).__module__}.{type(provider).__qualname__}"
    key = fingerprint("tts-wav-v2", engine, text, "mini", "voice", 1.0, provider.sample_rate)
    wav_path = cache / f"{key}.wav"
    incomplete = wav_bytes(np.zeros(500, dtype=np.float32), provider.sample_rate)[:-40]
    wav_path.write_bytes(incomplete)
    checksum_path = wav_path.with_suffix(".sha256")
    checksum_path.write_text(digest_bytes(incomplete) + "\n", encoding="utf-8")

    result = synthesize_chunks(
        text,
        provider,
        model="mini",
        voice="voice",
        speed=1.0,
        pause_ms=0,
        cache=cache,
    )

    assert provider.calls == 1
    assert result.size == 500
    assert read_wav(wav_path.read_bytes(), provider.sample_rate).size == 500
    assert checksum_path.read_text(encoding="utf-8").strip() == digest_bytes(wav_path.read_bytes())
