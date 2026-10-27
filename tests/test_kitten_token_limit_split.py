"""Kitten's limit is in tokens, so a chunk it rejects is retried as shorter pieces."""

from __future__ import annotations

import numpy as np
import pytest

from pdf2audiobook.errors import AudioError
from pdf2audiobook.tts import KittenProvider

PRIVATE = "SYNTHETIC_PRIVATE_NARRATION_TEXT"


def provider_with_model(model) -> KittenProvider:
    provider = object.__new__(KittenProvider)
    provider.model = model
    provider.model_id = "synthetic-model"
    return provider


class Backend:
    available_voices = ["Luna"]

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.calls: list[str] = []

    def generate(self, text, *, voice, speed):
        self.calls.append(text)
        if len(text) > self.limit:
            raise RuntimeError(f"invalid expand shape {text}")
        return np.full(len(text), 0.1, dtype=np.float32)


def test_a_rejected_chunk_is_spoken_as_shorter_pieces_in_order() -> None:
    backend = Backend(limit=120)
    provider = provider_with_model(backend)
    text = " ".join(f"word{i:02d}" for i in range(45))  # about 315 characters
    audio = provider.generate(text, voice="Luna", speed=1.0)
    spoken = [call for call in backend.calls if len(call) <= 120]
    assert len(spoken) >= 3
    assert " ".join(spoken) == text
    assert audio.ndim == 1 and audio.size > sum(len(piece) for piece in spoken)


def test_a_chunk_the_model_accepts_is_not_split() -> None:
    backend = Backend(limit=400)
    provider = provider_with_model(backend)
    provider.generate("A short sentence that fits.", voice="Luna", speed=1.0)
    assert backend.calls == ["A short sentence that fits."]


def test_a_failure_that_splitting_cannot_fix_is_a_sanitized_error() -> None:
    backend = Backend(limit=0)
    provider = provider_with_model(backend)
    text = f"{PRIVATE} " * 8
    with pytest.raises(AudioError, match="Kitten speech generation failed") as raised:
        provider.generate(text, voice="Luna", speed=1.0)
    assert PRIVATE not in str(raised.value)
    assert raised.value.__cause__ is None
    assert len(backend.calls) < 40  # bounded retries, not an unbounded split


def test_one_unbreakable_token_fails_without_splitting() -> None:
    backend = Backend(limit=10)
    provider = provider_with_model(backend)
    with pytest.raises(AudioError):
        provider.generate("x" * 100, voice="Luna", speed=1.0)
    assert backend.calls == ["x" * 100]
