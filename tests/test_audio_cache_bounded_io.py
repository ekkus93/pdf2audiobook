"""Bound untrusted WAV cache reads and generated per-chunk audio sizes."""

from __future__ import annotations

import wave

import numpy as np
import pytest

from pdf2audiobook.audio import read_wav, synthesize_chunks
from pdf2audiobook.errors import AudioError


class StubVoice:
    sample_rate = 24000

    def __init__(self, size: int = 100):
        self.calls = 0
        self.size = size

    def generate(self, text: str, *, voice: str, speed: float) -> np.ndarray:
        self.calls += 1
        return np.full(self.size, 0.125, dtype=np.float32)


def _synthesize(tmp_path, provider: StubVoice):
    return synthesize_chunks(
        "A short, synthetic spoken sentence.",
        provider,
        model="synthetic",
        voice="Test",
        speed=1.0,
        pause_ms=0,
        cache=tmp_path,
    )


def test_oversized_checksum_sidecar_regenerates_without_unbounded_read(monkeypatch, tmp_path):
    voice = StubVoice()
    _synthesize(tmp_path, voice)
    sidecar = next(tmp_path.glob("*.sha256"))
    sidecar.write_bytes(b"x" * 10000)
    # The sidecar is never read via Path.read_text/read_bytes, which could
    # load attacker-sized content into memory.
    from pathlib import Path

    original_read_bytes = Path.read_bytes
    original_read_text = Path.read_text

    def reject_sidecar_unbounded_read(path):
        if path == sidecar:
            raise AssertionError("unbounded checksum sidecar read")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", reject_sidecar_unbounded_read)

    def reject_sidecar_text_read(path, *args, **kwargs):
        if path == sidecar:
            raise AssertionError("unbounded sidecar text read")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", reject_sidecar_text_read)
    _synthesize(tmp_path, voice)
    assert voice.calls == 2
    with sidecar.open("rb") as saved:
        assert len(saved.read(66)) == 65
    _synthesize(tmp_path, voice)
    assert voice.calls == 2


def test_oversized_wav_is_rejected_before_cache_replay(monkeypatch, tmp_path):
    voice = StubVoice()
    _synthesize(tmp_path, voice)
    wav_path = next(tmp_path.glob("*.wav"))
    wav_path.write_bytes(b"x" * 2048)
    monkeypatch.setattr("pdf2audiobook.audio._MAX_CACHED_WAV_BYTES", 512)
    _synthesize(tmp_path, voice)
    assert voice.calls == 2


def test_generated_chunk_exceeding_cache_bound_fails_with_progress(monkeypatch, tmp_path):
    monkeypatch.setattr("pdf2audiobook.audio._MAX_CACHED_WAV_BYTES", 256)
    voice = StubVoice(size=200)
    progress = tmp_path / "progress.json"
    with pytest.raises(AudioError, match="TTS chunk exceeds safe WAV cache limit"):
        synthesize_chunks(
            "Synthetic short text.",
            voice,
            model="synthetic",
            voice="Test",
            speed=1.0,
            pause_ms=0,
            cache=tmp_path,
            progress_file=progress,
        )
    assert voice.calls == 1
    assert not list(tmp_path.glob("*.wav"))
    assert '"status": "failed"' in progress.read_text(encoding="utf-8")


def test_wave_parser_error_does_not_chain_untrusted_diagnostics(monkeypatch):
    marker = "SYNTHETIC_PRIVATE_AUDIO_ERROR_414"

    def broken_open(*args, **kwargs):
        raise wave.Error(marker)

    monkeypatch.setattr("pdf2audiobook.audio.wave.open", broken_open)
    with pytest.raises(AudioError, match="Cached WAV is invalid or unsupported") as raised:
        read_wav(b"RIFFbad", 24000)
    assert marker not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True
