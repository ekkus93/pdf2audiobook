"""Direct Kitten adapter calls enforce finite speed limits without a model."""

from __future__ import annotations

import math

import numpy as np
import pytest

from pdf2audiobook.errors import AudioError
from pdf2audiobook.tts import KittenProvider


class StubKitten:
    available_voices = ["Jasper"]

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, float]] = []

    def generate(self, text: str, *, voice: str, speed: float) -> np.ndarray:
        self.calls.append((text, voice, speed))
        return np.array([0.0, 0.25, -0.25], dtype=np.float32)


@pytest.mark.parametrize(
    "speed",
    [0, -1, 3.01, math.nan, math.inf, -math.inf, True, False, "1.0", None],
)
def test_invalid_direct_speed_fails_before_model_call(speed: object) -> None:
    provider = object.__new__(KittenProvider)
    model = StubKitten()
    provider.model = model
    with pytest.raises(AudioError, match="speed must be finite"):
        provider.generate("Synthetic narration.", voice="Jasper", speed=speed)
    assert model.calls == []


@pytest.mark.parametrize("speed", [0.5, 1.0, 3.0])
def test_valid_direct_speed_preserves_model_call(speed: float) -> None:
    provider = object.__new__(KittenProvider)
    model = StubKitten()
    provider.model = model
    samples = provider.generate("Synthetic narration.", voice="Jasper", speed=speed)
    assert model.calls == [("Synthetic narration.", "Jasper", speed)]
    assert samples.tolist() == pytest.approx([0.0, 0.25, -0.25])
