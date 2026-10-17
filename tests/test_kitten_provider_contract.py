"""Kitten adapter contract tests without downloading or importing a real model."""

import sys
import types

import numpy as np
import pytest

from pdf2audiobook.errors import AudioError
from pdf2audiobook.tts import KittenProvider, TTSProvider


def _install_fake_kitten(monkeypatch):
    loaded = []

    class FakeKittenTTS:
        available_voices = ["Jasper", "Luna"]

        def __init__(self, model_id):
            loaded.append(model_id)

        def generate(self, text, *, voice, speed):
            return np.full(2400, 0.1, dtype=np.float32)

    fake = types.ModuleType("kittenml")
    fake.KittenTTS = FakeKittenTTS
    monkeypatch.setitem(sys.modules, "kittenml", fake)
    return loaded, FakeKittenTTS


def test_kitten_model_alias_and_valid_voice(monkeypatch):
    loaded, _ = _install_fake_kitten(monkeypatch)
    provider = KittenProvider("mini")
    assert loaded == ["KittenML/kitten-tts-mini-0.8"]
    assert provider.sample_rate == 24000
    samples = provider.generate("Hello world.", voice="Jasper", speed=1.0)
    assert samples.shape == (2400,)
    assert np.isfinite(samples).all()


def test_kitten_custom_model_id_is_preserved(monkeypatch):
    loaded, _ = _install_fake_kitten(monkeypatch)
    KittenProvider("custom/model")
    assert loaded == ["custom/model"]


def test_kitten_invalid_voice_rejected_before_synthesis(monkeypatch):
    _install_fake_kitten(monkeypatch)
    provider = KittenProvider("nano")
    with pytest.raises(AudioError, match="Unknown Kitten voice"):
        provider.generate("Hello", voice="Missing", speed=1.0)
    with pytest.raises(AudioError, match="empty text chunk"):
        provider.generate("   ", voice="Jasper", speed=1.0)


def test_kitten_model_load_failure_is_actionable(monkeypatch):
    _, fake = _install_fake_kitten(monkeypatch)

    def fail_load(self, model_id):
        raise RuntimeError("model not installed")

    monkeypatch.setattr(fake, "__init__", fail_load)
    with pytest.raises(AudioError, match="Could not load Kitten TTS model"):
        KittenProvider("mini")


def test_kitten_invalid_audio_is_rejected(monkeypatch):
    _, fake = _install_fake_kitten(monkeypatch)

    def bad_audio(self, text, *, voice, speed):
        return np.array([float("nan")], dtype=np.float32)

    monkeypatch.setattr(fake, "generate", bad_audio)
    with pytest.raises(AudioError, match="empty or invalid speech audio"):
        KittenProvider("mini").generate("Hello", voice="Jasper", speed=1.0)


def test_tts_protocol_discovery_health_and_chunk_limit(monkeypatch):
    _install_fake_kitten(monkeypatch)
    provider = KittenProvider("mini")
    assert isinstance(provider, TTSProvider)
    assert provider.health() is True
    assert "mini" in provider.list_models()
    assert provider.model_id in provider.list_models()
    assert provider.list_voices() == ["Jasper", "Luna"]
    assert provider.max_chars_per_chunk == 350
    with pytest.raises(AudioError, match="chunk exceeds"):
        provider.generate("A" * 351, voice="Jasper", speed=1.0)
