"""Opt-in real Kitten smoke test; normal test runs never load or download a model."""

import importlib.util
import os

import numpy as np
import pytest

from pdf2audiobook.audio import read_wav, wav_bytes
from pdf2audiobook.tts import KittenProvider


@pytest.mark.skipif(
    os.environ.get("PDF2AUDIOBOOK_KITTEN_SMOKE") != "1",
    reason="set PDF2AUDIOBOOK_KITTEN_SMOKE=1 to load the real Kitten model",
)
@pytest.mark.skipif(
    importlib.util.find_spec("kittenml") is None, reason="kitten extra is not installed"
)
def test_real_kitten_synthesizes_a_short_synthetic_phrase():
    provider = KittenProvider("mini")
    samples = provider.generate("This is a synthetic Kitten smoke test.", voice="Jasper", speed=1.0)
    encoded = wav_bytes(samples, provider.sample_rate)
    decoded = read_wav(encoded, provider.sample_rate)
    assert isinstance(decoded, np.ndarray)
    assert decoded.ndim == 1
    assert decoded.size > 0
    assert np.isfinite(decoded).all()
