"""TTS transient failures use bounded retries and failed progress status."""

import json

import numpy as np
import pytest

import pdf2audiobook.audio as audio
from pdf2audiobook.errors import AudioError


class FlakyProvider:
    sample_rate = 24000
    max_chars_per_chunk = 350

    def __init__(self, failures):
        self.failures = failures
        self.calls = 0

    def generate(self, text, *, voice, speed):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("private narration must not appear")
        return np.ones(24, dtype=np.float32)


def _synthesize(provider, tmp_path, max_retries=2):
    return audio.synthesize_chunks(
        "A retryable sentence.",
        provider,
        model="stub",
        voice="voice",
        speed=1,
        pause_ms=0,
        cache=tmp_path / "cache",
        progress_file=tmp_path / "progress.json",
        max_retries=max_retries,
    )


def test_transient_tts_failure_retries_and_completes(monkeypatch, tmp_path):
    monkeypatch.setattr(audio.time, "sleep", lambda _seconds: None)
    provider = FlakyProvider(failures=1)
    result = _synthesize(provider, tmp_path)
    assert provider.calls == 2
    assert result.size == 24
    assert json.loads((tmp_path / "progress.json").read_text())["status"] == "completed"


def test_persistent_tts_failure_stops_after_configured_retries(monkeypatch, tmp_path):
    monkeypatch.setattr(audio.time, "sleep", lambda _seconds: None)
    provider = FlakyProvider(failures=9)
    with pytest.raises(AudioError, match="TTS synthesis failed") as raised:
        _synthesize(provider, tmp_path, max_retries=2)
    assert provider.calls == 3
    assert "private narration" not in str(raised.value)
    progress = json.loads((tmp_path / "progress.json").read_text())
    assert progress["status"] == "failed"
    assert progress["chunks"][0]["status"] == "failed"
