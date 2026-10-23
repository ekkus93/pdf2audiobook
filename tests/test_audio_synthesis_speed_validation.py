"""Validate public synthesis speed independently of the concrete TTS engine."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from pdf2audiobook.audio import synthesize_chunks
from pdf2audiobook.errors import AudioError


class UncheckedEngine:
    sample_rate = 24000
    max_chars_per_chunk = 350

    def __init__(self):
        self.calls = 0

    def generate(self, text, *, voice, speed):
        self.calls += 1
        return np.zeros(64, dtype=np.float32)


@pytest.mark.parametrize(
    "speed",
    [0, -1, 3.00001, math.nan, math.inf, -math.inf, True, False, None, "1", [], {}],
)
def test_invalid_speed_fails_before_synthesis_cache_and_progress(tmp_path: Path, speed):
    engine = UncheckedEngine()
    cache = tmp_path / "cache"
    progress = tmp_path / "progress.json"
    with pytest.raises(AudioError, match="speech speed") as raised:
        synthesize_chunks(
            "An ordinary synthetic passage.",
            engine,
            model="fixture",
            voice="fixture",
            speed=speed,
            pause_ms=0,
            cache=cache,
            progress_file=progress,
        )
    assert raised.value.__cause__ is None
    assert engine.calls == 0
    assert not progress.exists()
    assert not list(tmp_path.rglob("*.wav"))


@pytest.mark.parametrize("speed", [0.25, 1, 3.0])
def test_valid_speed_remains_supported_and_reusable(tmp_path: Path, speed):
    engine = UncheckedEngine()
    opts = dict(
        model="fixture",
        voice="fixture",
        speed=speed,
        pause_ms=0,
        cache=tmp_path,
    )
    first = synthesize_chunks("An ordinary synthetic passage.", engine, **opts)
    second = synthesize_chunks("An ordinary synthetic passage.", engine, **opts)
    assert engine.calls == 1
    assert np.array_equal(first, second)
