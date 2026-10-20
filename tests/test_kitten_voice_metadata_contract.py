"""Fail-closed validation of direct Kitten voice requests and metadata."""

import numpy as np
import pytest

from pdf2audiobook.errors import AudioError
from pdf2audiobook.tts import KittenProvider


class StubModel:
    def __init__(self, voices):
        self.available_voices = voices
        self.calls = []

    def generate(self, text, *, voice, speed):
        self.calls.append((text, voice, speed))
        return np.zeros(24, dtype=np.float32)


def provider_with_voices(voices):
    provider = KittenProvider.__new__(KittenProvider)
    provider.model = StubModel(voices)
    return provider


@pytest.mark.parametrize("voice", [None, False, 42, "", "  "])
def test_invalid_voice_is_rejected_before_model_invocation(voice):
    provider = provider_with_voices(["alice"])
    with pytest.raises(AudioError, match="nonempty string") as raised:
        provider.generate("synthetic narration", voice=voice, speed=1.0)
    assert raised.value.__cause__ is None
    assert provider.model.calls == []


@pytest.mark.parametrize("voices", ["alice-and-bob", 42, True])
def test_invalid_voice_collection_fails_closed(voices):
    provider = provider_with_voices(voices)
    assert provider.list_voices() == []
    with pytest.raises(AudioError, match="Could not validate Kitten voice") as raised:
        provider.generate("synthetic narration", voice="alice", speed=1.0)
    assert raised.value.__cause__ is None
    assert provider.model.calls == []


@pytest.mark.parametrize("voices", [["alice"], ("alice",), {"alice": object()}])
def test_supported_voice_collections_still_synthesize(voices):
    provider = provider_with_voices(voices)
    audio = provider.generate("synthetic narration", voice="alice", speed=1.0)
    assert audio.shape == (24,)
    assert provider.model.calls == [("synthetic narration", "alice", 1.0)]


def test_nonempty_known_voice_collection_rejects_unknown_voice():
    provider = provider_with_voices(["alice"])
    with pytest.raises(AudioError, match="Unknown Kitten voice"):
        provider.generate("synthetic narration", voice="bob", speed=1.0)
    assert provider.model.calls == []
