"""Adversarial TTS engine properties cannot leak data or change synthesis rate."""

from pathlib import Path

import numpy as np
import pytest

from pdf2audiobook.audio import synthesize_chunks
from pdf2audiobook.errors import AudioError

PRIVATE = "SYNTHETIC_PRIVATE_MODEL_DETAILS_278"


class Engine:
    max_chars_per_chunk = 350

    def __init__(self):
        self.calls = 0

    def generate(self, text, *, voice, speed):
        self.calls += 1
        return np.zeros(1200, dtype=np.float32)


class BrokenRate(Engine):
    @property
    def sample_rate(self):
        raise RuntimeError(f"backend returned {PRIVATE}")


class BrokenChunkLimit(Engine):
    sample_rate = 24000

    @property
    def max_chars_per_chunk(self):
        raise RuntimeError(f"backend returned {PRIVATE}")


@pytest.mark.parametrize(
    ("engine_class", "message"),
    [
        (BrokenRate, "Could not inspect TTS provider audio settings"),
        (BrokenChunkLimit, "Could not inspect TTS provider chunk limit"),
    ],
)
def test_provider_property_failures_are_sanitized_and_nonmutating(
    tmp_path: Path, engine_class, message: str
):
    provider = engine_class()
    progress = tmp_path / "progress.json"
    with pytest.raises(AudioError, match=message) as raised:
        synthesize_chunks(
            "Synthetic sample sentence.",
            provider,
            model="test",
            voice="test",
            speed=1.0,
            pause_ms=100,
            cache=tmp_path / "cache",
            progress_file=progress,
        )
    assert PRIVATE not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True
    assert provider.calls == 0
    assert not progress.exists()
    assert not list(tmp_path.rglob("*.wav"))


class SingleReadRate(Engine):
    def __init__(self):
        super().__init__()
        self.rate_reads = 0

    @property
    def sample_rate(self):
        self.rate_reads += 1
        if self.rate_reads != 1:
            raise RuntimeError(f"rate property re-read: {PRIVATE}")
        return 24000


def test_synthesis_uses_one_validated_rate_snapshot(tmp_path: Path):
    provider = SingleReadRate()
    result = synthesize_chunks(
        "Synthetic sample sentence.",
        provider,
        model="test",
        voice="test",
        speed=1.0,
        pause_ms=100,
        cache=tmp_path / "cache",
        progress_file=tmp_path / "progress.json",
    )
    assert result.size > 0
    assert provider.rate_reads == 1
    assert provider.calls == 1
