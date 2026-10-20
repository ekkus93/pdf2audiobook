"""Offline Kitten adapter contract tests; never load or download a real model."""

import sys
from types import ModuleType

import numpy as np
import pytest

from pdf2audiobook.errors import AudioError
from pdf2audiobook.tts import KittenProvider

SENTINEL = "PRIVATE_SYNTHETIC_BOOK_TEXT_101"


def fake_kitten(monkeypatch, result):
    module = ModuleType("kittenml")

    class FakeKitten:
        available_voices = ["Jasper"]

        def __init__(self, model_id):
            self.model_id = model_id

        def generate(self, text, *, voice, speed):
            return result

    module.KittenTTS = FakeKitten
    monkeypatch.setitem(sys.modules, "kittenml", module)
    return KittenProvider("mini")


@pytest.mark.parametrize(
    "invalid",
    [
        np.array(0.2, dtype=np.float32),
        np.array([[0.1, -0.1]], dtype=np.float32),
        np.array([[0.1], [-0.1]], dtype=np.float32),
        np.zeros((1, 1, 2), dtype=np.float32),
    ],
)
def test_kitten_rejects_non_mono_audio_without_flattening(monkeypatch, invalid):
    provider = fake_kitten(monkeypatch, invalid)
    with pytest.raises(AudioError, match="non-mono speech audio"):
        provider.generate("Synthetic sentence.", voice="Jasper", speed=1.0)


@pytest.mark.parametrize("invalid", [np.array([]), np.array([np.nan]), np.array([np.inf])])
def test_kitten_rejects_empty_or_nonfinite_audio(monkeypatch, invalid):
    provider = fake_kitten(monkeypatch, invalid)
    with pytest.raises(AudioError, match="empty or invalid speech audio"):
        provider.generate("Synthetic sentence.", voice="Jasper", speed=1.0)


def test_kitten_accepts_valid_mono_and_clips_to_pcm_range(monkeypatch):
    provider = fake_kitten(monkeypatch, np.array([-1.5, -0.25, 0.25, 1.5]))
    result = provider.generate("Synthetic sentence.", voice="Jasper", speed=1.0)
    assert result.ndim == 1
    assert result.dtype == np.float32
    np.testing.assert_array_equal(result, [-1.0, -0.25, 0.25, 1.0])


def test_kitten_conversion_does_not_echo_private_audio_data(monkeypatch):
    provider = fake_kitten(monkeypatch, [SENTINEL])
    with pytest.raises(AudioError) as raised:
        provider.generate("Synthetic sentence.", voice="Jasper", speed=1.0)
    assert str(raised.value) == "Kitten speech generation failed; verify model and voice"
    assert SENTINEL not in str(raised.value)
    assert raised.value.__cause__ is None
