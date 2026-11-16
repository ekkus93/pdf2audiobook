"""Typed contracts for post-synthesis audio verification (spec docs/PDF2AUDIOBOOK_AUDIO_VERIFICATION_SPEC.md).

Nothing here imports an ASR package: backends live in their own modules and load their
models only when asked, so ordinary conversion never touches them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

# The three independent model families (spec §1), by the names the CLI uses.
ModelName = Literal["whisper", "wav2vec2", "vosk"]
MODEL_NAMES: tuple[ModelName, ...] = ("whisper", "wav2vec2", "vosk")

# A chapter's outcome (spec §2). Never "correct" or "verified": ASR is evidence, not truth.
ChapterStatus = Literal[
    "no_mismatch_detected", "possible_mismatch", "model_disagreement", "verification_unavailable"
]
DifferenceKind = Literal["insertion", "omission", "substitution"]
ModelOutcome = Literal["ok", "unavailable", "failed"]

# Machine-readable reasons a chapter or model could not be verified.
REASONS = (
    "audio_missing",  # no MP3 for the chapter
    "audio_stale",  # the MP3 no longer matches the chapter text or settings
    # The chapter file or its pronunciations differ from what was spoken (synthesis ledger):
    # comparing would judge the audio against text that was never said (AVF1).
    "narration_not_spoken",
    "audio_undecodable",  # FFmpeg couldn't read the chapter's MP3 (AVF4)
    "no_models",  # no model was ready to run
    "unsupported_language",  # the voice isn't English (spec §12)
    "model_not_installed",  # the backend's package is missing
    "model_not_downloaded",  # its weights are missing or don't match the pinned revision
    "model_failed",  # the backend raised while transcribing
    "cancelled",  # stopped before this chapter or model finished
)


class Cancelled(Exception):
    """A backend saw the stop signal; the caller decides what that means."""


@dataclass(frozen=True)
class Word:
    """One transcribed word with its time in the chapter audio, when the backend gives one."""

    text: str
    start: float | None = None
    end: float | None = None


@dataclass(frozen=True)
class Transcript:
    model: ModelName
    words: tuple[Word, ...]


@dataclass(frozen=True)
class Readiness:
    """Whether a model can run on this machine, without loading it (spec §4, `asr list`)."""

    model: ModelName
    family: str
    model_id: str
    revision: str
    package: str
    package_version: str | None
    weights_present: bool
    size_bytes: int
    location: str
    reason: str | None = None

    @property
    def ready(self) -> bool:
        return self.package_version is not None and self.weights_present and self.reason is None


@runtime_checkable
class AsrBackend(Protocol):
    """A local speech recognizer behind one small interface (spec §4)."""

    name: ModelName

    def readiness(self) -> Readiness: ...

    def transcribe(self, wav: Path, *, should_stop: Callable[[], bool]) -> Transcript:
        """Transcribe a 16 kHz mono WAV; raise `Cancelled` soon after `should_stop()` is true."""
        ...


@dataclass(frozen=True)
class Difference:
    """One place where a model's transcript differs from the expected narration.

    `ref_start`/`ref_end` index the reference words (an insertion has `ref_start == ref_end`);
    `start`/`end` are seconds in the chapter audio, from the model's word times.
    """

    model: ModelName
    kind: DifferenceKind
    ref_start: int
    ref_end: int
    expected: str
    heard: str
    start: float | None
    end: float | None


@dataclass(frozen=True)
class Flag:
    """A difference two or more model families agree on (`possible_mismatch`), or one model
    alone saw (`model_disagreement`)."""

    kind: DifferenceKind
    ref_start: int
    ref_end: int
    expected: str
    heard: dict[ModelName, str]
    models: tuple[ModelName, ...]
    start: float | None
    end: float | None
    confirmed: bool


@dataclass(frozen=True)
class ModelRun:
    model: ModelName
    outcome: ModelOutcome
    reason: str | None = None
    seconds: float | None = None
    word_count: int | None = None


@dataclass(frozen=True)
class ChapterResult:
    number: int
    status: ChapterStatus
    reason: str | None
    models: tuple[ModelRun, ...]
    flags: tuple[Flag, ...] = ()
    # Fewer than three families voted: never reported as a three-way majority (spec §3).
    partial: bool = False
    audio_sha256: str | None = None
    reference_sha256: str | None = None
    duration_seconds: float | None = None
    transcripts: dict[ModelName, tuple[Word, ...]] = field(default_factory=dict)
