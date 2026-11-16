"""Local inference adapters for the three ASR families, behind `AsrBackend` (spec §4).

Each backend imports its library and loads its model only on first use, transcribes a 16 kHz
mono WAV in windows of at most 30 s (split at the quietest moment near each boundary, so no
word is cut), checks the stop signal between windows, and keeps third-party output off
stdout so `--json` stays parseable. Limits from spec §13: one model at a time, torch on the
GPU when there is one, else on the CPU with a bounded number of threads.
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import subprocess
import wave
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import numpy as np

from pdf2audiobook.errors import AudioError
from pdf2audiobook.verification.contracts import (
    AsrBackend,
    Cancelled,
    ModelName,
    Readiness,
    Transcript,
    Word,
)
from pdf2audiobook.verification.models import SPECS, model_dir, readiness

RATE = 16_000
WINDOW_SECONDS = 30.0
# Look this far back from a window's end for the quietest place to cut.
SEARCH_SECONDS = 5.0
# Samples are read from the decoded WAV this many seconds at a time (AVF4).
BLOCK_SECONDS = 1.0
DEFAULT_THREADS = 4


def _quiet() -> contextlib.redirect_stdout[io.StringIO]:
    """Third-party libraries print progress; keep stdout for our own JSON."""
    return contextlib.redirect_stdout(io.StringIO())


def decode(source: Path, target: Path) -> Path:
    """Decode any audio FFmpeg reads to 16 kHz mono 16-bit WAV."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(source), "-ac", "1", "-ar", str(RATE),
             "-c:a", "pcm_s16le", str(target)],
            capture_output=True,
            check=False,
        )  # fmt: skip
    except OSError:
        raise AudioError("FFmpeg executable not found in PATH") from None
    if result.returncode != 0:
        raise AudioError("Could not decode chapter audio for verification")
    return target


def open_wav(path: Path) -> wave.Wave_read:
    """Open a decoded WAV, refusing any format the backends weren't built for. Reads nothing."""
    source = wave.open(str(path), "rb")  # noqa: SIM115 - the caller closes it
    try:
        if (
            source.getframerate() != RATE
            or source.getnchannels() != 1
            or source.getsampwidth() != 2
        ):
            raise AudioError("Verification audio must be 16 kHz mono 16-bit")
    except BaseException:
        source.close()
        raise
    return source


def _cut(samples: np.ndarray, origin: int, start: int, size: int, search: int, frame: int) -> int:
    """The quietest 20 ms in the last `search` samples before `start + size`.

    `samples[0]` is absolute sample `origin`; the search never reaches before `start + size -
    search`, so a streaming caller needs only the samples from there on.
    """
    lo, hi = start + size - search, start + size
    segment = samples[lo - origin : hi - origin]
    energy = np.square(segment[: len(segment) // frame * frame]).reshape(-1, frame).mean(axis=1)
    return lo + int(np.argmin(energy)) * frame + frame // 2


def windows(audio: np.ndarray, window: float = WINDOW_SECONDS) -> list[tuple[int, int]]:
    """Split points no more than `window` seconds apart, each at the quietest 20 ms nearby."""
    size, search, frame = int(window * RATE), int(SEARCH_SECONDS * RATE), RATE // 50
    spans: list[tuple[int, int]] = []
    start = 0
    while len(audio) - start > size:
        cut = _cut(audio, 0, start, size, search, frame)
        spans.append((start, cut))
        start = cut
    spans.append((start, len(audio)))
    return spans


def iter_windows(
    path: Path,
    window: float = WINDOW_SECONDS,
    *,
    observe: Callable[[int], None] | None = None,
) -> Iterator[tuple[int, np.ndarray]]:
    """Yield `(start_sample, samples)` for each window of a decoded WAV, reading as it goes.

    The same split points as `windows()`, but the chapter is never held whole: the buffer
    keeps one window, the search region before its end and one read block, so its peak size
    is about `window + SEARCH_SECONDS + BLOCK_SECONDS` seconds of audio however long the file
    is. `observe`, if given, receives the buffer's length after each read (for tests). Closing
    the generator closes the file.
    """
    size, search, frame = int(window * RATE), int(SEARCH_SECONDS * RATE), RATE // 50
    block = int(BLOCK_SECONDS * RATE)
    with contextlib.closing(open_wav(path)) as source:
        total = source.getnframes()
        buffer = np.empty(0, dtype=np.float32)
        origin = 0  # absolute sample index of buffer[0]
        read_to = 0  # absolute sample index of the next sample to read
        start = 0  # absolute start of the next window

        def fill(upto: int) -> None:
            nonlocal buffer, read_to
            target = min(upto, total)
            while read_to < target:
                data = source.readframes(min(block, target - read_to))
                if not data:
                    break
                chunk = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
                buffer = np.concatenate((buffer, chunk))
                read_to += len(chunk)
                if observe is not None:
                    observe(len(buffer))

        while total - start > size:
            fill(start + size)
            cut = _cut(buffer, origin, start, size, search, frame)
            yield start, buffer[start - origin : cut - origin].copy()
            # The next window starts at the cut; nothing before it is needed again.
            buffer = buffer[cut - origin :]
            origin = start = cut
        fill(total)
        yield start, buffer[start - origin :].copy()


def _threads(threads: int) -> None:
    """Bound math-library threads; env vars only work before torch is first imported."""
    for variable in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(variable, str(threads))


def _torch_device(device: str, threads: int) -> str:
    import torch

    torch.set_num_threads(threads)
    if device == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    return device


class _Base:
    name: ModelName

    def __init__(
        self, root: Path | None = None, *, device: str = "auto", threads: int = DEFAULT_THREADS
    ) -> None:
        self.root = root
        self.device = device
        self.threads = threads
        self._model: Any = None

    def readiness(self) -> Readiness:
        return readiness(self.name, self.root)

    def folder(self) -> Path:
        return model_dir(self.name, self.root)

    def close(self) -> None:
        """Release the model so the next one has the memory (one model at a time)."""
        self._model = None
        with contextlib.suppress(Exception):
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def _windows(
        self, wav: Path, should_stop: Callable[[], bool]
    ) -> Iterator[tuple[float, np.ndarray]]:
        for start, piece in iter_windows(wav):
            if should_stop():
                raise Cancelled
            yield start / RATE, piece


class WhisperBackend(_Base):
    name: ModelName = "whisper"

    def _load(self) -> Any:
        if self._model is None:
            _threads(self.threads)
            with _quiet():
                import whisper

                device = _torch_device(self.device, self.threads)
                self._model = whisper.load_model(
                    str(self.folder() / SPECS["whisper"].files[0].name), device=device
                )
                self._fp16 = device == "cuda"
        return self._model

    def transcribe(self, wav: Path, *, should_stop: Callable[[], bool]) -> Transcript:
        model = self._load()
        words: list[Word] = []
        for offset, piece in self._windows(wav, should_stop):
            with _quiet():
                result = model.transcribe(
                    piece, language="en", word_timestamps=True, fp16=self._fp16, verbose=None,
                    condition_on_previous_text=False, temperature=0.0,
                )  # fmt: skip
            for segment in result.get("segments", []):
                for item in segment.get("words", []):
                    words.append(
                        Word(
                            item["word"].strip(),
                            round(float(offset + item["start"]), 3),
                            round(float(offset + item["end"]), 3),
                        )
                    )
        return Transcript("whisper", tuple(words))


class Wav2Vec2Backend(_Base):
    name: ModelName = "wav2vec2"

    def _load(self) -> Any:
        if self._model is None:
            _threads(self.threads)
            with _quiet():
                import transformers

                transformers.logging.set_verbosity_error()
                transformers.logging.disable_progress_bar()
                from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

                device = _torch_device(self.device, self.threads)
                folder = str(self.folder())
                processor = Wav2Vec2Processor.from_pretrained(folder, local_files_only=True)
                model = (
                    Wav2Vec2ForCTC.from_pretrained(folder, local_files_only=True).to(device).eval()
                )
                self._model = (processor, model, device)
        return self._model

    def transcribe(self, wav: Path, *, should_stop: Callable[[], bool]) -> Transcript:
        import torch

        processor, model, device = self._load()
        ratio = model.config.inputs_to_logits_ratio / RATE
        words: list[Word] = []
        for offset, piece in self._windows(wav, should_stop):
            with _quiet():
                inputs = processor(piece, sampling_rate=RATE, return_tensors="pt").input_values.to(
                    device
                )
                with torch.inference_mode():
                    logits = model(inputs).logits
                ids = torch.argmax(logits, dim=-1)[0].cpu()
                decoded = processor.decode(ids, output_word_offsets=True)
            for item in decoded.word_offsets:
                words.append(
                    Word(
                        item["word"],
                        round(float(offset + item["start_offset"] * ratio), 3),
                        round(float(offset + item["end_offset"] * ratio), 3),
                    )
                )
        return Transcript("wav2vec2", tuple(words))


class VoskBackend(_Base):
    name: ModelName = "vosk"
    # 4,000 frames is 0.25 s: the stop signal is checked at least that often.
    FRAMES = 4_000

    def _load(self) -> Any:
        if self._model is None:
            with _quiet():
                from vosk import Model, SetLogLevel

                SetLogLevel(-1)
                self._model = Model(str(self.folder() / SPECS["vosk"].unpack_to))  # type: ignore[operator]
        return self._model

    def transcribe(self, wav: Path, *, should_stop: Callable[[], bool]) -> Transcript:
        from vosk import KaldiRecognizer

        recognizer = KaldiRecognizer(self._load(), RATE)
        recognizer.SetWords(True)
        words: list[Word] = []

        def take(result: str) -> None:
            for item in json.loads(result).get("result", []):
                words.append(Word(item["word"], float(item["start"]), float(item["end"])))

        with contextlib.closing(open_wav(wav)) as source:
            while data := source.readframes(self.FRAMES):
                if should_stop():
                    raise Cancelled
                if recognizer.AcceptWaveform(data):
                    take(recognizer.Result())
        take(recognizer.FinalResult())
        return Transcript("vosk", tuple(words))


BACKENDS: dict[ModelName, type[_Base]] = {
    "whisper": WhisperBackend,
    "wav2vec2": Wav2Vec2Backend,
    "vosk": VoskBackend,
}


def backend(name: ModelName, root: Path | None = None, **options: Any) -> AsrBackend:
    created: AsrBackend = BACKENDS[name](root, **options)  # type: ignore[assignment]
    return created


logging.getLogger("numba").setLevel(logging.WARNING)
