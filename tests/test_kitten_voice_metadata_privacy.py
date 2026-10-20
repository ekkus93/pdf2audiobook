"""Kitten voice discovery and validation must not expose backend diagnostics."""

from __future__ import annotations

import numpy as np
import pytest

from pdf2audiobook.errors import AudioError
from pdf2audiobook.tts import KittenProvider

PRIVATE = "SYNTHETIC_PRIVATE_KITTEN_BACKEND_275"


def provider_with_model(model) -> KittenProvider:
    # Test the adapter without importing KittenML or downloading a voice model.
    provider = object.__new__(KittenProvider)
    provider.model = model
    provider.model_id = "synthetic-model"
    return provider


def test_unknown_voice_error_does_not_echo_user_voice_or_backend_metadata():
    class Backend:
        available_voices = ["Jasper", PRIVATE]

        def generate(self, *args, **kwargs):
            raise AssertionError("must not synthesize with unknown voice")

    provider = provider_with_model(Backend())
    with pytest.raises(AudioError, match="Unknown Kitten voice") as raised:
        provider.generate("Synthetic sample.", voice="UNTRUSTED_VOICE_" + PRIVATE, speed=1.0)
    assert PRIVATE not in str(raised.value)
    assert raised.value.__cause__ is None


def test_voice_metadata_property_exception_is_sanitized_and_discovery_is_safe():
    class Backend:
        @property
        def available_voices(self):
            raise RuntimeError(f"model metadata exposed {PRIVATE}")

        def generate(self, *args, **kwargs):
            return np.ones(100, dtype=np.float32)

    provider = provider_with_model(Backend())
    assert provider.list_voices() == []
    assert provider.health()
    with pytest.raises(AudioError, match="Could not validate Kitten voice") as raised:
        provider.generate("Synthetic sample.", voice="Jasper", speed=1.0)
    assert PRIVATE not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


def test_untrusted_voice_membership_exception_is_sanitized():
    class BrokenVoices:
        def __bool__(self):
            return True

        def __contains__(self, _voice):
            raise RuntimeError(PRIVATE)

    class Backend:
        available_voices = BrokenVoices()

        def generate(self, *args, **kwargs):
            raise AssertionError("must not synthesize without voice validation")

    provider = provider_with_model(Backend())
    with pytest.raises(AudioError, match="Could not validate Kitten voice") as raised:
        provider.generate("Synthetic sample.", voice="Jasper", speed=1.0)
    assert PRIVATE not in str(raised.value)
    assert raised.value.__cause__ is None


def test_health_returns_false_when_backend_generate_property_raises():
    class Backend:
        @property
        def generate(self):
            raise RuntimeError(PRIVATE)

    assert provider_with_model(Backend()).health() is False
