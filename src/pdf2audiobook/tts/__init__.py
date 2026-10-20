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
    max_chars_per_chunk: int

    def list_models(self) -> list[str]:
        """Return available model identifiers without downloading models."""

    def list_voices(self) -> list[str]:
        """Return discoverable voice IDs, or [] if the engine cannot enumerate."""

    def health(self) -> bool:
        """Report whether the loaded engine is callable, without synthesizing."""

    def generate(self, text: str, *, voice: str, speed: float) -> np.ndarray:
        """Return mono float audio in [-1,1] at sample_rate."""


class KittenProvider:
    """Lazy initialization avoids model downloads during CLI import and tests."""

    sample_rate = 24000
    max_chars_per_chunk = 350

    def __init__(self, model: str = "mini"):
        try:
            from kittenml import KittenTTS  # type: ignore[import-not-found]
        except ImportError as exc:
            raise AudioError(
                "Kitten TTS is not installed. Run 'uv sync --extra kitten' first."
            ) from exc
        model_id = KITTEN_MODEL_ALIASES.get(model, model)
        self.model_id = model_id
        try:
            self.model = KittenTTS(model_id)
        except Exception:
            # Third-party exceptions can echo model paths, credentials or
            # supplied text. Do not surface their contents or chained context.
            raise AudioError("Could not load Kitten TTS model; verify the model and installation") from None

    def list_models(self) -> list[str]:
        return list(dict.fromkeys([*KITTEN_MODEL_ALIASES, self.model_id]))

    def list_voices(self) -> list[str]:
        voices = getattr(self.model, "available_voices", None)
        if isinstance(voices, (list, tuple, dict)):
            return [name for name in voices if isinstance(name, str)]
        return []

    def health(self) -> bool:
        return callable(getattr(self.model, "generate", None))

    def generate(self, text: str, *, voice: str, speed: float) -> np.ndarray:
        if len(text) > self.max_chars_per_chunk:
            raise AudioError("Kitten text chunk exceeds configured engine limit")
        if not text.strip():
            raise AudioError("Cannot synthesize an empty text chunk")
        voices = getattr(self.model, "available_voices", None)
        if voices and voice not in voices:
            raise AudioError(f"Unknown Kitten voice {voice!r}; available: {voices}")
        try:
            result = np.asarray(
                self.model.generate(text, voice=voice, speed=speed), dtype=np.float32
            )
        except Exception:
            # The backend may include private narration text in its exception.
            raise AudioError("Kitten speech generation failed; verify model and voice") from None
        # The TTSProvider contract requires mono PCM. Flattening multi-channel
        # samples would interleave channels and corrupt duration and playback.
        if result.ndim != 1:
            raise AudioError("Kitten returned non-mono speech audio")
        if result.size == 0 or not np.isfinite(result).all():
            raise AudioError("Kitten returned empty or invalid speech audio")
        return np.clip(result, -1.0, 1.0)
