"""TTS numeric conversion and provider failures must not echo narration."""

from pathlib import Path

import numpy as np
import pytest

from pdf2audiobook.audio import synthesize_chunks, wav_bytes
from pdf2audiobook.errors import AudioError

PRIVATE = "SYNTHETIC_BOOK_TEXT_SENTINEL_9021"


class BrokenArray:
    def __array__(self, dtype=None, copy=None):
        raise RuntimeError(f"untrusted TTS text {PRIVATE}")


@pytest.mark.parametrize(
    "invalid",
    [
        [PRIVATE],
        np.array([PRIVATE], dtype=object),
        BrokenArray(),
    ],
)
def test_untrusted_audio_conversion_does_not_echo_contents(invalid):
    with pytest.raises(AudioError) as raised:
        wav_bytes(invalid, 24000)
    assert "TTS returned invalid audio sample data" in str(raised.value)
    assert PRIVATE not in str(raised.value)
    assert raised.value.__cause__ is None


class FailingProvider:
    sample_rate = 24000
    max_chars_per_chunk = 350

    def generate(self, text, *, voice, speed):
        raise RuntimeError(f"backend failed on {text} {PRIVATE}")


def test_provider_error_does_not_echo_narration_and_marks_progress_failed(tmp_path: Path):
    from pdf2audiobook.workspace import read_json

    progress = tmp_path / "progress.json"
    with pytest.raises(AudioError) as raised:
        synthesize_chunks(
            f"This is a private fictional example. {PRIVATE}",
            FailingProvider(),
            model="fixture", voice="fixture", speed=1.0,
            pause_ms=0, cache=tmp_path / "cache", progress_file=progress,
        )
    assert str(raised.value) == "TTS synthesis failed; verify model and voice"
    assert PRIVATE not in str(raised.value)
    assert raised.value.__cause__ is None
    record = read_json(progress)
    assert record["status"] == "failed"
    assert record["chunks"][0]["status"] == "failed"
    assert not list((tmp_path / "cache").glob("*.wav"))
