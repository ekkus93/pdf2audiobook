"""Kitten backend failures must not echo book text or private runtime details."""

import sys
from types import ModuleType

import pytest

from pdf2audiobook.errors import AudioError
from pdf2audiobook.tts import KittenProvider


def test_kitten_model_load_failure_does_not_expose_backend_exception(monkeypatch):
    secret = "PRIVATE_MODEL_PATH_OR_TOKEN"
    module = ModuleType("kittenml")

    class BrokenKitten:
        def __init__(self, model_id):
            raise RuntimeError(f"{secret}: {model_id}")

    module.KittenTTS = BrokenKitten
    monkeypatch.setitem(sys.modules, "kittenml", module)
    with pytest.raises(AudioError, match="Could not load Kitten TTS model") as failure:
        KittenProvider("mini")
    assert secret not in str(failure.value)
    assert failure.value.__suppress_context__ is True


def test_kitten_generation_failure_does_not_expose_narration(monkeypatch):
    secret = "PRIVATE_BOOK_SENTENCE_DO_NOT_ECHO"
    module = ModuleType("kittenml")

    class BrokenKitten:
        available_voices = ["Jasper"]

        def __init__(self, model_id):
            self.model_id = model_id

        def generate(self, text, *, voice, speed):
            raise RuntimeError(f"backend echoed: {text}")

    module.KittenTTS = BrokenKitten
    monkeypatch.setitem(sys.modules, "kittenml", module)
    provider = KittenProvider("mini")
    with pytest.raises(AudioError, match="Kitten speech generation failed") as failure:
        provider.generate(secret, voice="Jasper", speed=1.0)
    assert secret not in str(failure.value)
    assert failure.value.__suppress_context__ is True
