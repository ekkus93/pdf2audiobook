"""A reference-bound provider using cancelable local model inference."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from pdf2audiobook.errors import AudioError
from pdf2audiobook.tts import KITTEN_BUILTIN_VOICES
from pdf2audiobook.tts.catalog import require_model
from pdf2audiobook.tts.cloning import ReferenceVoice
from pdf2audiobook.tts.private import PrivateDirectory
from pdf2audiobook.tts.worker_client import WorkerClient

MODEL_PREPARATION_TIMEOUT = 900.0

BUILTIN_VOICES = list(KITTEN_BUILTIN_VOICES)


def _read_worker_audio(path: Path) -> np.ndarray:
    try:
        if not path.is_file() or path.stat().st_size > 24000 * 120 * 4 + 1024:
            raise ValueError
        audio = np.load(path, allow_pickle=False)
        if (
            audio.ndim != 1
            or audio.dtype != np.float32
            or not audio.size
            or not np.isfinite(audio).all()
        ):
            raise ValueError
        return np.clip(audio, -1, 1)
    except (OSError, ValueError):
        raise AudioError("Local voice model returned invalid speech audio") from None


def change_speed(samples: np.ndarray, speed: float) -> np.ndarray:
    if not 0.1 <= speed <= 3 or not np.isfinite(speed):
        raise AudioError("Speech speed must be finite and in [0.1, 3]")
    if speed == 1:
        return samples
    maximum_seconds = 120 / speed
    factors = []
    while speed < 0.5:
        factors.append(0.5)
        speed /= 0.5
    while speed > 2:
        factors.append(2.0)
        speed /= 2.0
    factors.append(speed)
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-threads",
                "1",
                "-f",
                "f32le",
                "-ar",
                "24000",
                "-ac",
                "1",
                "-i",
                "pipe:0",
                "-af",
                ",".join(f"atempo={value}" for value in factors),
                "-t",
                str(maximum_seconds),
                "-f",
                "f32le",
                "pipe:1",
            ],
            input=samples.astype("<f4").tobytes(),
            capture_output=True,
            timeout=30,
        )
        audio = np.frombuffer(result.stdout, dtype="<f4").copy()
        if result.returncode or not audio.size or not np.isfinite(audio).all():
            raise ValueError
        return audio
    except (OSError, ValueError, subprocess.SubprocessError):
        raise AudioError("Could not adjust cloned speech speed") from None


class KittenCloneProvider:
    sample_rate = 24000
    max_chars_per_chunk = 350
    supports_voice_listing = False

    def __init__(self, reference: ReferenceVoice, *, temperature: float):
        require_model()
        self.temperature = temperature
        if reference.wav is None or reference.transcript is None:
            raise AudioError(
                "Provide the original voice reference to synthesize new audio",
                error_reason="voice_clone_unavailable",
            )
        self.reference = reference
        self.client = WorkerClient()
        try:
            self.client.request(
                {
                    "command": "prepare",
                    "reference": str(reference.wav),
                    "transcript": reference.transcript,
                },
                timeout=MODEL_PREPARATION_TIMEOUT,
            )
        except BaseException:
            self.close()
            raise

    def health(self) -> bool:
        return self.client.process.poll() is None

    def list_models(self) -> list[str]:
        return ["kitten2"]

    def list_voices(self) -> list[str]:
        return []

    def generate(self, text: str, *, voice: str, speed: float) -> np.ndarray:
        if voice != self.reference.key or not text.strip() or len(text) > self.max_chars_per_chunk:
            raise AudioError(
                "Invalid reference voice selection or narration chunk",
                error_reason="voice_selection_conflict",
            )
        with PrivateDirectory("audio") as folder:
            output = Path(folder) / "audio.npy"
            self.client.request(
                {
                    "command": "generate",
                    "reference": str(self.reference.wav),
                    "transcript": self.reference.transcript,
                    "text": text,
                    "temperature": self.temperature,
                    "output": str(output),
                }
            )
            return change_speed(_read_worker_audio(output), speed)

    def close(self) -> None:
        self.client.close()


class Kitten2BuiltinProvider(KittenCloneProvider):
    """Keep explicit --no-clone-voice usable with a selected KittenTTS 2 model."""

    supports_voice_listing = True

    def __init__(self, *, temperature: float) -> None:
        require_model()
        self.temperature = temperature
        self.client = WorkerClient()
        try:
            self.client.request({"command": "load"}, timeout=MODEL_PREPARATION_TIMEOUT)
        except BaseException:
            self.close()
            raise

    def list_voices(self) -> list[str]:
        return list(BUILTIN_VOICES)

    def generate(self, text: str, *, voice: str, speed: float) -> np.ndarray:
        if voice not in BUILTIN_VOICES or not text.strip() or len(text) > self.max_chars_per_chunk:
            raise AudioError("Choose an available built-in voice and a nonempty narration chunk")
        with PrivateDirectory("audio") as folder:
            output = Path(folder) / "audio.npy"
            self.client.request(
                {
                    "command": "generate_builtin",
                    "voice": voice,
                    "text": text,
                    "temperature": self.temperature,
                    "output": str(output),
                }
            )
            return change_speed(_read_worker_audio(output), speed)
