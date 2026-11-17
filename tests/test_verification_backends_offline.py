"""Recognizer backends, offline (coverage round 3, TC1 / R1).

Each library a backend imports is replaced, for one test, by a stand-in installed in
`sys.modules`. The stand-ins return scripted words, so the window-offset, frame-time, device,
thread and cleanup arithmetic runs without torch, transformers, whisper or vosk, and without
model weights.
"""

from __future__ import annotations

import contextlib
import json
import sys
import types
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from pdf2audiobook.errors import AudioError
from pdf2audiobook.verification.backends import (
    RATE,
    VoskBackend,
    Wav2Vec2Backend,
    WhisperBackend,
    windows,
)
from pdf2audiobook.verification.contracts import Cancelled
from pdf2audiobook.verification.models import SPECS


@pytest.fixture(autouse=True)
def _restore_thread_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    # The backends set these with setdefault; setting then deleting makes monkeypatch restore them.
    for variable in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        monkeypatch.setenv(variable, "sentinel")
        monkeypatch.delenv(variable)


def _write(path: Path, audio: np.ndarray) -> Path:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    return path


def _long_audio(seconds: float) -> np.ndarray:
    """A tone with short silences, so the window split has several cut points."""
    t = np.arange(int(seconds * RATE)) / RATE
    audio = 0.3 * np.sin(2 * np.pi * 220 * t)
    for at in (27.0, 56.5):
        if at < seconds:
            audio[int(at * RATE) : int((at + 0.2) * RATE)] = 0
    return audio.astype(np.float32)


class _Tensor:
    """Stands in for a torch tensor: indexing and moving it change nothing."""

    def __getitem__(self, _index: object) -> _Tensor:
        return self

    def cpu(self) -> _Tensor:
        return self

    def to(self, _device: object) -> _Tensor:
        return self


def _install_torch(monkeypatch: pytest.MonkeyPatch, *, cuda: bool = False) -> dict[str, Any]:
    log: dict[str, Any] = {"threads": [], "emptied": 0}
    torch = types.ModuleType("torch")
    torch.set_num_threads = lambda n: log["threads"].append(n)  # type: ignore[attr-defined]
    torch.cuda = types.SimpleNamespace(  # type: ignore[attr-defined]
        is_available=lambda: cuda,
        empty_cache=lambda: log.__setitem__("emptied", log["emptied"] + 1),
    )
    torch.inference_mode = contextlib.nullcontext  # type: ignore[attr-defined]
    torch.argmax = lambda logits, dim: logits  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", torch)
    return log


def _install_whisper(
    monkeypatch: pytest.MonkeyPatch, words_per_window: list[list[tuple[str, float, float]]]
) -> dict[str, list[Any]]:
    """`words_per_window`: the (word, start, end) each window's transcription reports, in call order."""
    log: dict[str, list[Any]] = {"loaded": [], "calls": []}
    script = list(words_per_window)

    class Model:
        def transcribe(self, piece: np.ndarray, **options: Any) -> dict[str, Any]:
            log["calls"].append(len(piece))
            words = script.pop(0)
            return {
                "segments": [
                    {"words": [{"word": f" {w} ", "start": s, "end": e} for w, s, e in words]}
                ]
            }

    def load_model(path: str, device: str) -> Model:
        log["loaded"].append((path, device))
        return Model()

    whisper = types.ModuleType("whisper")
    whisper.load_model = load_model  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "whisper", whisper)
    return log


def _install_transformers(
    monkeypatch: pytest.MonkeyPatch, frames_per_window: list[list[tuple[str, int, int]]]
) -> dict[str, Any]:
    """`frames_per_window`: the (word, start frame, end frame) each window's decoding reports."""
    log: dict[str, Any] = {"loaded": [], "device": None}
    script = list(frames_per_window)

    class Config:
        inputs_to_logits_ratio = 320

    class Processor:
        @staticmethod
        def from_pretrained(folder: str, local_files_only: bool) -> Processor:
            log["loaded"].append(("processor", folder, local_files_only))
            return Processor()

        def __call__(self, piece: np.ndarray, sampling_rate: int, return_tensors: str) -> Any:
            return types.SimpleNamespace(input_values=_Tensor())

        def decode(self, ids: object, output_word_offsets: bool) -> Any:
            words = script.pop(0)
            return types.SimpleNamespace(
                word_offsets=[{"word": w, "start_offset": s, "end_offset": e} for w, s, e in words]
            )

    class Model:
        config = Config()

        @staticmethod
        def from_pretrained(folder: str, local_files_only: bool) -> Model:
            log["loaded"].append(("model", folder, local_files_only))
            return Model()

        def __call__(self, inputs: object) -> Any:
            return types.SimpleNamespace(logits=_Tensor())

        def to(self, device: str) -> Model:
            log["device"] = device
            return self

        def eval(self) -> Model:
            return self

    transformers = types.ModuleType("transformers")
    transformers.logging = types.SimpleNamespace(  # type: ignore[attr-defined]
        set_verbosity_error=lambda: None, disable_progress_bar=lambda: None
    )
    transformers.Wav2Vec2Processor = Processor  # type: ignore[attr-defined]
    transformers.Wav2Vec2ForCTC = Model  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    return log


def _install_vosk(
    monkeypatch: pytest.MonkeyPatch, words_per_block: list[list[tuple[str, float, float]]]
) -> dict[str, list[Any]]:
    """`words_per_block`: the words each accepted block reports, in order; the last is the final result."""
    log: dict[str, list[Any]] = {"models": [], "blocks": []}
    script = [list(words) for words in words_per_block]

    class Model:
        def __init__(self, path: str) -> None:
            log["models"].append(path)

    class KaldiRecognizer:
        def __init__(self, model: Model, rate: int) -> None:
            self.pending: list[tuple[str, float, float]] = []

        def SetWords(self, enabled: bool) -> None:  # noqa: N802 - the library's name
            pass

        def AcceptWaveform(self, data: bytes) -> bool:  # noqa: N802
            log["blocks"].append(len(data))
            if not script:
                return False
            self.pending = script.pop(0)
            return True

        def Result(self) -> str:  # noqa: N802
            return json.dumps(
                {"result": [{"word": w, "start": s, "end": e} for w, s, e in self.pending]}
            )

        def FinalResult(self) -> str:  # noqa: N802
            return json.dumps({"result": []})

    vosk = types.ModuleType("vosk")
    vosk.Model = Model  # type: ignore[attr-defined]
    vosk.KaldiRecognizer = KaldiRecognizer  # type: ignore[attr-defined]
    vosk.SetLogLevel = lambda level: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "vosk", vosk)
    return log


# --- TC1.02: Whisper reports every window's words at the window's offset --------------------


def test_whisper_reports_each_window_at_its_offset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = _long_audio(65)
    wav = _write(tmp_path / "long.wav", audio)
    starts = [start / RATE for start, _ in windows(audio)]
    assert len(starts) >= 3
    _install_torch(monkeypatch)
    log = _install_whisper(monkeypatch, [[("hello", 1.0, 1.4)] for _ in starts])

    transcript = WhisperBackend(tmp_path).transcribe(wav, should_stop=lambda: False)

    assert len(log["calls"]) == len(starts)
    assert [word.text for word in transcript.words] == ["hello"] * len(starts)
    assert [word.start for word in transcript.words] == [round(s + 1.0, 3) for s in starts]
    assert [word.end for word in transcript.words] == [round(s + 1.4, 3) for s in starts]


# --- TC1.03: Wav2Vec2 converts frames to seconds and adds the window offset -----------------


def test_wav2vec2_adds_each_window_offset_to_frame_times(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = _long_audio(65)
    wav = _write(tmp_path / "long.wav", audio)
    starts = [start / RATE for start, _ in windows(audio)]
    assert len(starts) >= 3
    _install_torch(monkeypatch)
    _install_transformers(monkeypatch, [[("cat", 10, 15)] for _ in starts])

    transcript = Wav2Vec2Backend(tmp_path, device="cpu").transcribe(wav, should_stop=lambda: False)

    ratio = 320 / RATE  # the model's frames per 320 samples, in seconds
    assert [word.text for word in transcript.words] == ["cat"] * len(starts)
    assert [word.start for word in transcript.words] == [round(s + 10 * ratio, 3) for s in starts]
    assert [word.end for word in transcript.words] == [round(s + 15 * ratio, 3) for s in starts]


# --- TC1.04: Vosk keeps its own word times and checks the stop signal between blocks --------


def test_vosk_keeps_word_times_and_reads_the_model_it_was_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 10,000 samples: blocks of 4,000, 4,000 and 2,000 frames.
    wav = _write(tmp_path / "short.wav", _long_audio(10_000 / RATE))
    log = _install_vosk(monkeypatch, [[("gull", 0.5, 0.9)], [("point", 1.2, 1.6)]])

    transcript = VoskBackend(tmp_path).transcribe(wav, should_stop=lambda: False)

    assert [(w.text, w.start, w.end) for w in transcript.words] == [
        ("gull", 0.5, 0.9),
        ("point", 1.2, 1.6),
    ]
    assert log["blocks"] == [8000, 8000, 4000]  # 2 bytes per frame, in blocks of 4,000 frames
    assert log["models"][0].endswith(SPECS["vosk"].unpack_to)  # type: ignore[operator]


def test_vosk_stops_between_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wav = _write(tmp_path / "short.wav", _long_audio(10_000 / RATE))
    _install_vosk(monkeypatch, [[("gull", 0.5, 0.9)]])
    checks = iter([False, True])

    with pytest.raises(Cancelled):
        VoskBackend(tmp_path).transcribe(wav, should_stop=lambda: next(checks))


# --- TC1.05: device choice, thread limits and cleanup -------------------------------------


@pytest.mark.parametrize(
    ("device", "cuda", "expected"),
    [("auto", True, "cuda"), ("auto", False, "cpu"), ("cpu", True, "cpu")],
)
def test_whisper_chooses_the_device_and_limits_threads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, device: str, cuda: bool, expected: str
) -> None:
    torch_log = _install_torch(monkeypatch, cuda=cuda)
    whisper_log = _install_whisper(monkeypatch, [])
    model = WhisperBackend(tmp_path, device=device, threads=3)

    model._load()

    assert whisper_log["loaded"][0][1] == expected
    assert model._fp16 == (expected == "cuda")
    assert torch_log["threads"] == [3]


def test_wav2vec2_loads_from_the_folder_without_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_torch(monkeypatch)
    log = _install_transformers(monkeypatch, [])

    Wav2Vec2Backend(tmp_path, device="cpu")._load()

    assert [entry[0] for entry in log["loaded"]] == ["processor", "model"]
    assert all(entry[2] is True for entry in log["loaded"])  # local_files_only
    assert log["device"] == "cpu"


def test_close_releases_the_model_and_the_gpu_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    torch_log = _install_torch(monkeypatch, cuda=True)
    _install_whisper(monkeypatch, [])
    model = WhisperBackend(tmp_path, device="auto")
    model._load()
    assert model._model is not None

    model.close()

    assert model._model is None
    assert torch_log["emptied"] == 1


def test_close_on_cpu_leaves_the_gpu_cache_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    torch_log = _install_torch(monkeypatch, cuda=False)
    _install_whisper(monkeypatch, [])
    model = WhisperBackend(tmp_path, device="cpu")
    model._load()

    model.close()

    assert model._model is None
    assert torch_log["emptied"] == 0


# --- TC1.06: a model that fails to load --------------------------------------------------


def test_a_model_that_fails_to_load_raises_a_content_free_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_torch(monkeypatch)

    def load_model(path: str, device: str) -> None:
        raise RuntimeError(f"cannot read weights at {path}")

    whisper = types.ModuleType("whisper")
    whisper.load_model = load_model  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "whisper", whisper)
    wav = _write(tmp_path / "short.wav", _long_audio(2))

    with pytest.raises(AudioError) as raised:
        WhisperBackend(tmp_path).transcribe(wav, should_stop=lambda: False)

    assert str(tmp_path) not in str(raised.value)


def test_the_backend_factory_builds_each_family_with_its_options(tmp_path: Path) -> None:
    from pdf2audiobook.verification.backends import backend

    built = backend("whisper", tmp_path, device="cpu", threads=2)

    assert isinstance(built, WhisperBackend)
    assert (built.device, built.threads) == ("cpu", 2)


def test_readiness_reports_missing_weights_without_loading_the_library(tmp_path: Path) -> None:
    # No library is installed for this test, and no weights exist under tmp_path: the report says so
    # and nothing is imported or loaded.
    state = WhisperBackend(tmp_path).readiness()

    assert state.ready is False
    assert state.reason is not None
