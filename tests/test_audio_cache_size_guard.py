"""Adversarial cached WAV metadata must not allocate unbounded memory."""

import stat
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from pdf2audiobook.audio import read_wav, synthesize_chunks
from pdf2audiobook.errors import AudioError


def test_wav_rejects_unbounded_frame_count_before_read(monkeypatch) -> None:
    class OversizedWav:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getframerate(self):
            return 24000

        def getnchannels(self):
            return 1

        def getsampwidth(self):
            return 2

        def getnframes(self):
            return 2**31

        def readframes(self, _count):
            pytest.fail("Unbounded WAV frames were read")

    monkeypatch.setattr("pdf2audiobook.audio.wave.open", lambda *_args, **_kw: OversizedWav())
    with pytest.raises(AudioError, match="excessive audio frames"):
        read_wav(b"RIFF synthetic", 24000)


def test_oversized_cached_chunk_is_regenerated_without_reading_it(
    monkeypatch, tmp_path: Path
) -> None:
    class StubTTS:
        sample_rate = 24000
        max_chars_per_chunk = 350

        def __init__(self):
            self.calls = 0

        def generate(self, text, *, voice, speed):
            self.calls += 1
            return np.ones(240, dtype=np.float32) * 0.1

    provider = StubTTS()
    cache = tmp_path / "cache"
    first = synthesize_chunks(
        "A short synthetic passage.", provider, model="fixture", voice="voice",
        speed=1.0, pause_ms=0, cache=cache,
    )
    assert provider.calls == 1
    assert first.size > 0
    original_stat = Path.stat
    original_read_bytes = Path.read_bytes

    def fake_stat(path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if path.suffix == ".wav" and path.parent == cache:
            return SimpleNamespace(
                st_mode=stat.S_IFREG | 0o644,
                st_size=129 * 1024 * 1024,
            )
        return result

    def guarded_read(path):
        if path.suffix == ".wav" and path.parent == cache:
            pytest.fail("Oversized cached WAV was read into memory")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "stat", fake_stat)
    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    second = synthesize_chunks(
        "A short synthetic passage.", provider, model="fixture", voice="voice",
        speed=1.0, pause_ms=0, cache=cache,
    )
    assert provider.calls == 2
    assert np.array_equal(first, second)
