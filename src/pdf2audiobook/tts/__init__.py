"""Replaceable text-to-speech provider interface and Kitten implementation."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from pdf2audiobook.errors import AudioError

KITTEN_MODEL_ALIASES = {
    "mini": "KittenML/kitten-tts-mini-0.8",
    "micro": "KittenML/kitten-tts-micro-0.8",
    "nano": "KittenML/kitten-tts-nano-0.8",
}


@runtime_checkable
class TTSProvider(Protocol):
    sample_rate: int

    def generate(self, text: str, *, voice: str, speed: float) -> np.ndarray:
        """Return mono float audio in [-1,1] at sample_rate."""


class KittenProvider:
    """Lazy initialization avoids model downloads during CLI import and tests."""

    sample_rate = 24000

    def __init__(self, model: str = "mini"):
        try:
            from kittenml import KittenTTS
        except ImportError as exc:
            raise AudioError(
                "Kitten TTS is not installed. Run 'uv sync --extra kitten' first."
            ) from exc
        model_id = KITTEN_MODEL_ALIASES.get(model, model)
        try:
            self.model = KittenTTS(model_id)
        except Exception as exc:
            raise AudioError(f"Could not load Kitten TTS model {model_id}: {exc}") from exc

    def generate(self, text: str, *, voice: str, speed: float) -> np.ndarray:
        if not text.strip():
            raise AudioError("Cannot synthesize an empty text chunk")
        voices = getattr(self.model, "available_voices", None)
        if voices and voice not in voices:
            raise AudioError(f"Unknown Kitten voice {voice!r}; available: {voices}")
        try:
            result = np.asarray(
                self.model.generate(text, voice=voice, speed=speed), dtype=np.float32
            ).reshape(-1)
        except Exception as exc:
            raise AudioError(f"Kitten speech generation failed: {exc}") from exc
        if result.size == 0 or not np.isfinite(result).all():
            raise AudioError("Kitten returned empty or invalid speech audio")
        return np.clip(result, -1.0, 1.0)
