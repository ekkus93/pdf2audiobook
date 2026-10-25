"""Replaceable text-to-speech provider interface and Kitten implementation."""

from __future__ import annotations

import contextlib
import io
import json
import math
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
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


def _quiet_stdout() -> contextlib.redirect_stdout[io.StringIO]:
    """Discard backend prints: kittenml echoes every narration chunk to stdout,
    which would leak book text into logs and corrupt --json reports."""
    return contextlib.redirect_stdout(io.StringIO())


class KittenProvider:
    """Lazy initialization avoids model downloads during CLI import and tests."""

    sample_rate = 24000
    max_chars_per_chunk = 350

    def __init__(self, model: str = "mini"):
        try:
            from kittenml import KittenTTS  # type: ignore[import-not-found]
        except ImportError:
            raise AudioError(
                "Kitten TTS is not installed. Run 'uv sync --extra kitten' first."
            ) from None
        model_id = KITTEN_MODEL_ALIASES.get(model, model)
        self.model_id = model_id
        try:
            with _quiet_stdout():
                self.model = KittenTTS(model_id)
        except Exception:
            # Third-party exceptions can echo model paths, credentials or
            # supplied text. Do not surface their contents or chained context.
            raise AudioError(
                "Could not load Kitten TTS model; verify the model and installation"
            ) from None

    def list_models(self) -> list[str]:
        return list(dict.fromkeys([*KITTEN_MODEL_ALIASES, self.model_id]))

    def list_voices(self) -> list[str]:
        try:
            voices = getattr(self.model, "available_voices", None)
            if isinstance(voices, (list, tuple, dict)):
                return [name for name in voices if isinstance(name, str)]
        except Exception:
            # A backend property may raise with local paths or model details.
            pass
        return []

    def health(self) -> bool:
        try:
            return callable(getattr(self.model, "generate", None))
        except Exception:
            return False

    def generate(self, text: str, *, voice: str, speed: float) -> np.ndarray:
        # The protocol is callable outside the Pydantic/CLI configuration path.
        # Validate the same finite speed bounds before invoking third-party code.
        if (
            isinstance(speed, bool)
            or not isinstance(speed, (int, float))
            or not math.isfinite(speed)
            or not 0 < speed <= 3
        ):
            raise AudioError("Kitten speech speed must be finite and in (0, 3]")
        if not isinstance(voice, str) or not voice.strip():
            # Direct protocol callers may bypass typed configuration.
            raise AudioError("Kitten voice must be a nonempty string")
        if len(text) > self.max_chars_per_chunk:
            raise AudioError("Kitten text chunk exceeds configured engine limit")
        if not text.strip():
            raise AudioError("Cannot synthesize an empty text chunk")
        try:
            voices = getattr(self.model, "available_voices", None)
            if voices is not None and not isinstance(voices, (list, tuple, dict)):
                # A string is not a voice collection: substring membership
                # would otherwise approve unknown voice IDs.
                raise TypeError("invalid voice metadata type")
            known_voice = not voices or voice in voices
        except Exception:
            # Third-party voice metadata may include private model diagnostics.
            raise AudioError("Could not validate Kitten voice availability") from None
        if not known_voice:
            raise AudioError("Unknown Kitten voice; check the available voices with doctor")
        try:
            with _quiet_stdout():
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


class PiperProvider:
    """Optional adapter for an externally installed Piper CLI and voice model.

    Piper remains outside the default dependency set: users install the engine
    and voice model separately, then configure the model's ONNX path.
    """

    max_chars_per_chunk = 350

    def __init__(self, model_path: str | Path, executable: str = "piper"):
        self.model_path = Path(model_path).expanduser()
        self.executable = executable
        if not self.model_path.is_file():
            raise AudioError("Piper model file is unavailable; configure a local ONNX voice model")
        if shutil.which(executable) is None:
            raise AudioError("Piper CLI is unavailable; install piper-tts and check PATH")
        config_path = Path(f"{self.model_path}.json")
        try:
            with config_path.open("rb") as stream:
                raw_config = stream.read(1_048_577)
            if len(raw_config) > 1_048_576:
                raise ValueError("oversized model configuration")
            config = json.loads(raw_config)
            rate = config["audio"]["sample_rate"]
        except (OSError, ValueError, KeyError, TypeError):
            raise AudioError("Piper voice configuration is missing a valid sample rate") from None
        if isinstance(rate, bool) or not isinstance(rate, int) or not 8000 <= rate <= 192000:
            raise AudioError("Piper voice sample rate must be an integer from 8000 to 192000")
        self.sample_rate = rate

    def list_models(self) -> list[str]:
        return [str(self.model_path)]

    def list_voices(self) -> list[str]:
        return []

    def health(self) -> bool:
        return self.model_path.is_file() and shutil.which(self.executable) is not None

    def generate(self, text: str, *, voice: str, speed: float) -> np.ndarray:
        if not isinstance(text, str) or not text.strip() or len(text) > self.max_chars_per_chunk:
            raise AudioError("Piper text must be nonempty and within its chunk limit")
        if (
            isinstance(speed, bool)
            or not isinstance(speed, (int, float))
            or not math.isfinite(speed)
            or not 0 < speed <= 3
        ):
            raise AudioError("Piper speech speed must be finite and in (0, 3]")
        args = [self.executable, "--model", str(self.model_path)]
        if voice:
            if not isinstance(voice, str) or not voice.isdecimal() or len(voice) > 10:
                raise AudioError("Piper speaker ID must be a nonnegative integer")
            args.extend(("--speaker", str(int(voice))))
        args.extend(("--length-scale", str(1.0 / speed)))
        try:
            with tempfile.TemporaryDirectory(prefix="pdf2audiobook-piper-") as directory:
                output = Path(directory) / "chunk.wav"
                args.extend(("--output_file", str(output)))
                subprocess.run(
                    args,
                    input=text,
                    capture_output=True,
                    text=True,
                    timeout=300,
                    check=True,
                )
                if not output.is_file() or output.stat().st_size > 128 * 1024 * 1024:
                    raise AudioError("Piper returned missing or oversized audio")
                with wave.open(str(output), "rb") as wav:
                    if (
                        wav.getframerate() != self.sample_rate
                        or wav.getnchannels() != 1
                        or wav.getsampwidth() != 2
                    ):
                        raise AudioError("Piper returned unsupported audio format")
                    count = wav.getnframes()
                    if count <= 0 or count > 64 * 1024 * 1024:
                        raise AudioError("Piper returned empty or oversized audio")
                    data = wav.readframes(count)
                    if len(data) != count * 2:
                        raise AudioError("Piper returned truncated audio")
            return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32767.0
        except AudioError:
            raise
        except Exception:
            # Do not reflect backend errors: subprocess diagnostics can contain
            # the synthesized source text or local filesystem paths.
            raise AudioError("Piper speech generation failed; verify the model and CLI") from None
