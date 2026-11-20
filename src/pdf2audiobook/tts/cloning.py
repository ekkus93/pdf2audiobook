"""Private reference snapshots and content identities, independent of model imports."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from pdf2audiobook.config import Settings
from pdf2audiobook.errors import AudioError, ConfigError
from pdf2audiobook.tts.catalog import (
    MANIFEST_SHA256,
    MODEL_ID,
    MODEL_REVISION,
    REQUIRED_PACKAGES,
    SDK_VERSION,
    package_versions,
)
from pdf2audiobook.tts.private import PrivateDirectory, worker_supported
from pdf2audiobook.workspace import fingerprint

RATE = 24000
MAX_REFERENCE_BYTES = 10 * 1024 * 1024
MAX_TRANSCRIPT_BYTES = 64 * 1024
PREPARATION = "pcm-s16le-mono-24000-v1"
GENERATION = {
    "schema_version": 1,
    "model_revision": MODEL_REVISION,
    "manifest_sha256": MANIFEST_SHA256,
    "sdk": SDK_VERSION,
    "backend": "torch",
    "cpu_threads": 2,
    "weights": "emb4",
    "decoder": "default",
    "preparation": PREPARATION,
    "speed_processing": "ffmpeg-atempo-v1",
    "preset": "stable",
    "seed": 0,
    "normalize": False,
    "language": "en",
}


def clone_error(message: str, reason: str = "voice_reference_invalid") -> ConfigError:
    return ConfigError(message, error_reason=reason)


def validate_clone_selection(settings: Settings) -> None:
    clone = settings.tts.voice_clone
    explicit = settings._clone_explicit
    if not clone.enabled:
        if explicit & {"reference_audio", "reference_text_file"}:
            raise clone_error("Reference options require --clone-voice")
        return
    if not worker_supported():
        raise clone_error(
            "Local voice cloning currently requires POSIX process and file-lock support",
            "voice_clone_unsupported",
        )
    if settings.tts.provider != "kitten" or settings.tts.kitten.model not in {"kitten2", MODEL_ID}:
        raise clone_error(
            "Voice cloning requires the full KittenTTS 2 model: use --tts-model kitten2",
            "voice_clone_unsupported",
        )
    if "voice" in explicit:
        raise clone_error("Choose --voice or --clone-voice, not both", "voice_selection_conflict")
    if not clone.reference_audio or not clone.reference_audio.strip():
        raise clone_error("Voice cloning needs --reference-audio or a configured recording")


def _snapshot_bytes(path_text: str, limit: int) -> bytes:
    if not path_text or "://" in path_text or "\0" in path_text:
        raise clone_error("Reference inputs must be readable local regular files")
    try:
        path = Path(path_text).expanduser()
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise clone_error("Reference input is not a regular file or exceeds its size limit")
            data = stream.read(limit + 1)
            after, current = os.fstat(stream.fileno()), path.stat()
            stream.seek(0)
            captured_again = stream.read(limit + 1)
        keys = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if data != captured_again or any(
            getattr(before, key) != getattr(other, key)
            for other in (after, current)
            for key in keys
        ):
            raise AudioError(
                "Reference input changed during capture", error_reason="voice_reference_changed"
            )
        if len(data) > limit:
            raise clone_error("Reference input exceeds its size limit")
        return data
    except (OSError, ValueError):
        raise clone_error("Reference inputs must be readable local regular files") from None


def normalize_transcript(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text or "\0" in text or len(text.encode("utf-8")) > MAX_TRANSCRIPT_BYTES:
        raise clone_error("Reference transcript must be nonempty UTF-8 text, at most 64 KiB")
    return text


def decode_reference(data: bytes, suffix: str) -> bytes:
    formats = {".wav": "wav", ".flac": "flac", ".mp3": "mp3"}
    if suffix.lower() not in formats:
        raise clone_error("Choose a WAV, FLAC or MP3 reference recording")
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-threads",
                "1",
                "-protocol_whitelist",
                "pipe",
                "-f",
                formats[suffix.lower()],
                "-i",
                "pipe:0",
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(RATE),
                "-t",
                "30.1",
                "-f",
                "f32le",
                "pipe:1",
            ],
            input=data,
            capture_output=True,
            timeout=20,
        )
        if result.returncode or len(result.stdout) % 4:
            raise ValueError("decode")
        samples = np.frombuffer(result.stdout, dtype="<f4")
        if not 5 * RATE <= samples.size <= 30 * RATE:
            raise clone_error("Reference recording must be between 5 and 30 seconds")
        if not np.isfinite(samples).all() or np.max(np.abs(samples)) < 1e-5:
            raise clone_error("Reference recording must contain finite, non-silent speech")
        if np.max(np.abs(samples)) > 1.01:
            raise clone_error("Reference recording has out-of-range audio samples")
        return np.rint(np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    except (OSError, ValueError, subprocess.SubprocessError):
        raise AudioError(
            "Could not decode reference recording; check the audio and FFmpeg installation",
            error_reason="voice_reference_invalid",
        ) from None


@dataclass
class ReferenceVoice:
    identity: dict[str, Any]
    wav: Path | None = field(default=None, repr=False)
    transcript: str | None = field(default=None, repr=False)
    temporary: PrivateDirectory | None = field(default=None, repr=False)
    kind: Literal["reference"] = field(default="reference", init=False)

    @property
    def key(self) -> str:
        return "clone:" + fingerprint(self.identity)

    def close(self) -> None:
        if self.temporary is not None:
            self.temporary.cleanup()
            self.temporary = None
        self.transcript = None
        self.wav = None


@dataclass(frozen=True)
class BuiltinVoice:
    name: str
    kind: Literal["builtin"] = field(default="builtin", init=False)


def snapshot_reference(settings: Settings, *, transcribe: bool = True) -> ReferenceVoice:
    validate_clone_selection(settings)
    clone = settings.tts.voice_clone
    assert clone.reference_audio is not None
    data = _snapshot_bytes(clone.reference_audio, MAX_REFERENCE_BYTES)
    pcm = decode_reference(data, Path(clone.reference_audio).suffix)
    temporary = PrivateDirectory("reference")
    try:
        path = Path(temporary.name) / "reference.wav"
        with wave.open(str(path), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(RATE)
            stream.writeframes(pcm)
        path.chmod(0o600)
        text, asr_identity = None, None
        if clone.reference_text_file is not None:
            try:
                text = normalize_transcript(
                    _snapshot_bytes(clone.reference_text_file, MAX_TRANSCRIPT_BYTES).decode("utf-8")
                )
            except UnicodeError:
                raise clone_error("Reference transcript must be UTF-8 text") from None
        elif transcribe:
            from pdf2audiobook.tts.worker_client import transcribe_reference

            text, asr_identity = transcribe_reference(path)
            text = normalize_transcript(text)
        identity = {
            **GENERATION,
            "reference_audio_sha256": hashlib.sha256(pcm).hexdigest(),
            "reference_text_sha256": hashlib.sha256(text.encode()).hexdigest() if text else None,
            "transcription": asr_identity,
            "backend_versions": {
                key: value for key, value in package_versions().items() if value is not None
            },
        }
        return ReferenceVoice(identity, path, text, temporary)
    except BaseException:
        temporary.cleanup()
        raise


def clone_metadata(settings: Settings) -> dict[str, Any] | None:
    reference = settings._clone_reference
    return (
        reference.identity
        if settings.tts.voice_clone.enabled and isinstance(reference, ReferenceVoice)
        else None
    )


def resolved_voice(settings: Settings, voice: str) -> BuiltinVoice | ReferenceVoice:
    if settings.tts.voice_clone.enabled and isinstance(settings._clone_reference, ReferenceVoice):
        return settings._clone_reference
    return BuiltinVoice(voice)


def clone_diagnostics(settings: Settings) -> dict[str, Any]:
    supported = settings.tts.provider == "kitten" and settings.tts.kitten.model in {
        "kitten2",
        MODEL_ID,
    }
    clone = settings.tts.voice_clone
    result: dict[str, Any] = {
        "supported": supported,
        "enabled": clone.enabled,
        "reference_configured": bool(clone.reference_audio),
        "transcript_configured": bool(clone.reference_text_file),
    }
    if supported:
        from pdf2audiobook.tts.catalog import model_readiness

        ready = model_readiness()
        result.update(
            {
                "model_ready": ready["ready"],
                "transcription_ready": ready["transcription_ready"],
                "ready": ready["ready"]
                and (
                    not clone.enabled
                    or bool(clone.reference_audio)
                    and (bool(clone.reference_text_file) or ready["transcription_ready"])
                ),
            }
        )
    return result


def complete_transcript(reference: ReferenceVoice) -> None:
    if reference.transcript is not None:
        return
    if reference.wav is None:
        raise AudioError(
            "Provide the original reference for new synthesis",
            error_reason="voice_clone_unavailable",
        )
    from pdf2audiobook.tts.worker_client import transcribe_reference

    text, asr = transcribe_reference(reference.wav)
    reference.transcript = normalize_transcript(text)
    digest = hashlib.sha256(reference.transcript.encode()).hexdigest()
    if digest == reference.identity.get("reference_text_sha256"):
        # Rehydrating the same words must retain the saved conditioning provenance.
        return
    reference.identity = {
        **reference.identity,
        "reference_text_sha256": digest,
        "transcription": asr,
    }


def valid_recorded_identity(value: object) -> bool:
    if not isinstance(value, dict) or any(
        value.get(key) != item for key, item in GENERATION.items()
    ):
        return False
    allowed = set(GENERATION) | {
        "reference_audio_sha256",
        "reference_text_sha256",
        "transcription",
        "backend_versions",
    }
    if set(value) != allowed:
        return False
    for name in ("reference_audio_sha256", "reference_text_sha256"):
        digest = value.get(name)
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            return False
    versions = value.get("backend_versions")
    if (
        not isinstance(versions, dict)
        or not set(versions).issubset(REQUIRED_PACKAGES)
        or any(not _public_version(value) for value in versions.values())
    ):
        return False
    current = package_versions()
    if any(current.get(key) is not None and current[key] != item for key, item in versions.items()):
        return False
    transcription = value.get("transcription")
    if transcription is not None:
        from pdf2audiobook.verification.models import SPECS, readiness

        if (
            not isinstance(transcription, dict)
            or set(transcription) != {"model", "package"}
            or not _public_version(transcription.get("package"))
            or transcription.get("model") != SPECS["whisper"].revision
        ):
            return False
        installed = readiness("whisper").package_version
        if installed is not None and installed != transcription.get("package"):
            return False
    return True


def _public_version(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9A-Za-z.+!_-]{1,128}", value) is not None
