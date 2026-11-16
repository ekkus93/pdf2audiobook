"""ASR backend adapters: offline behavior, plus opt-in real-model smoke tests (AV2.03, AV2.04).

The smoke tests run only with PDF2AUDIOBOOK_ASR_SMOKE=1, the backend's extra installed, its
weights fetched (`pdf2audiobook asr fetch`, or PDF2AUDIOBOOK_ASR_DIR pointing at them) and
Kitten installed to speak the test sentence. CI never runs them.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

from pdf2audiobook.verification import backends
from pdf2audiobook.verification.backends import (
    RATE,
    backend,
    decode,
    iter_windows,
    open_wav,
    windows,
)
from pdf2audiobook.verification.compare import differences, tokenize, tokenize_text
from pdf2audiobook.verification.contracts import Cancelled


def _write(path: Path, audio: np.ndarray, rate: int = RATE) -> Path:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    return path


def _samples(path: Path) -> np.ndarray:
    """The whole decoded file, for test expectations only: production never reads it whole."""
    with open_wav(path) as source:
        data = source.readframes(source.getnframes())
    return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0


def _speechlike(seconds: float, quiet_at: list[float]) -> np.ndarray:
    """A tone with short silences at the given times, standing in for speech and pauses."""
    t = np.arange(int(seconds * RATE)) / RATE
    audio = 0.3 * np.sin(2 * np.pi * 220 * t)
    for at in quiet_at:
        audio[int(at * RATE) : int((at + 0.2) * RATE)] = 0
    return audio.astype(np.float32)


def test_windows_cut_at_the_quietest_place_and_stay_short() -> None:
    audio = _speechlike(75, quiet_at=[27.0, 56.5])
    spans = windows(audio)
    assert spans[0][0] == 0 and spans[-1][1] == len(audio)
    assert all(b - a <= 30 * RATE for a, b in spans)
    assert all(spans[i][1] == spans[i + 1][0] for i in range(len(spans) - 1))
    cuts = [b / RATE for a, b in spans[:-1]]
    assert 27.0 <= cuts[0] <= 27.2 and 56.5 <= cuts[1] <= 56.7


def test_short_audio_is_one_window() -> None:
    assert windows(np.zeros(10 * RATE, dtype=np.float32)) == [(0, 10 * RATE)]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg not installed")
def test_decode_makes_16khz_mono(tmp_path: Path) -> None:
    tone = 0.3 * np.sin(2 * np.pi * 220 * np.arange(2 * 24000) / 24000)
    source = _write(tmp_path / "source.wav", tone.astype(np.float32), rate=24000)
    audio = _samples(decode(source, tmp_path / "decoded.wav"))
    assert abs(len(audio) / RATE - 2.0) < 0.05


def test_reading_other_formats_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="16 kHz mono"):
        open_wav(_write(tmp_path / "fast.wav", np.zeros(100, dtype=np.float32), rate=24000))


class _CountingWhisper(backends.WhisperBackend):
    """Whisper's windowing with a stand-in model: no torch, no weights."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def _load(self) -> object:
        backend = self

        class Model:
            def transcribe(self, piece: np.ndarray, **options: object) -> dict:
                backend.calls += 1
                return {"segments": [{"words": [{"word": " tone", "start": 0.5, "end": 0.9}]}]}

        self._fp16 = False
        return Model()


def test_word_times_include_the_window_offset(tmp_path: Path) -> None:
    wav = _write(tmp_path / "long.wav", _speechlike(65, quiet_at=[28.0, 57.0]))
    transcript = _CountingWhisper().transcribe(wav, should_stop=lambda: False)
    starts = [w.start for w in transcript.words]
    assert len(starts) == 3 and starts[0] == 0.5
    assert all(isinstance(s, float) for s in starts)
    assert 28.0 < starts[1] < 29.0 and 57.0 < starts[2] < 58.0


def test_a_stop_request_ends_transcription_between_windows(tmp_path: Path) -> None:
    wav = _write(tmp_path / "long.wav", _speechlike(65, quiet_at=[28.0, 57.0]))
    whisper = _CountingWhisper()
    checks = iter([False, True])
    with pytest.raises(Cancelled):
        whisper.transcribe(wav, should_stop=lambda: next(checks))
    assert whisper.calls == 1


def test_readiness_imports_no_asr_library(tmp_path: Path) -> None:
    code = (
        "import sys\n"
        "from pdf2audiobook.verification.backends import backend\n"
        f"states = [backend(n, __import__('pathlib').Path({str(tmp_path)!r})).readiness() for n in ('whisper', 'wav2vec2', 'vosk')]\n"
        "print([s.reason for s in states])\n"
        "print(sorted(m for m in ('whisper', 'vosk', 'transformers', 'torch') if m in sys.modules))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    reasons, loaded = result.stdout.strip().splitlines()
    assert "model_not_downloaded" in reasons or "model_not_installed" in reasons
    assert "None" not in reasons
    assert loaded == "[]"


# --- opt-in smoke tests with the real models ---------------------------------------------

SENTENCE = "The keeper climbed ninety two steps and wound the clockwork of the great lamp."


@pytest.fixture(scope="module")
def spoken(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if os.environ.get("PDF2AUDIOBOOK_ASR_SMOKE") != "1":
        pytest.skip("set PDF2AUDIOBOOK_ASR_SMOKE=1 to run the real ASR models")
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg not installed")
    pytest.importorskip("kittenml")
    from pdf2audiobook.tts import KittenProvider

    provider = KittenProvider("mini")
    audio = provider.generate(SENTENCE, voice="Jasper", speed=1.0)
    folder = tmp_path_factory.mktemp("asr")
    return decode(
        _write(folder / "kitten.wav", audio, rate=provider.sample_rate), folder / "speech.wav"
    )


@pytest.mark.parametrize("name", ["whisper", "wav2vec2", "vosk"])
def test_real_backend_transcribes_kitten_speech(spoken: Path, name: str) -> None:
    model = backend(name)
    state = model.readiness()
    if not state.ready:
        pytest.skip(f"{name} not ready: {state.reason}")
    transcript = model.transcribe(spoken, should_stop=lambda: False)
    model.close()
    assert transcript.model == name and transcript.words
    assert all(
        w.start is not None and w.end is not None and w.start <= w.end for w in transcript.words
    )
    found = differences(name, tokenize_text(SENTENCE), tokenize(transcript.words))
    assert [d for d in found if d.kind != "substitution"] == [], found


def test_streaming_windows_are_the_same_as_the_whole_file_split(tmp_path: Path) -> None:
    audio = _speechlike(200, quiet_at=[27.0, 56.5, 90.0, 121.3, 150.0])
    wav = _write(tmp_path / "long.wav", audio)
    streamed = [(start, start + len(piece)) for start, piece in iter_windows(wav)]
    assert streamed == windows(audio)
    # Each window's samples are exactly the file's samples there.
    decoded = _samples(wav)
    for start, piece in iter_windows(wav):
        assert np.array_equal(piece, decoded[start : start + len(piece)])


def _peak_buffer(path: Path) -> int:
    peak = 0

    def observe(length: int) -> None:
        nonlocal peak
        peak = max(peak, length)

    for _ in iter_windows(path, observe=observe):
        pass
    return peak


def test_the_buffer_does_not_grow_with_the_chapter(tmp_path: Path) -> None:
    short = _write(tmp_path / "two.wav", _speechlike(120, quiet_at=[27.0]))
    long = _write(tmp_path / "ten.wav", _speechlike(600, quiet_at=[27.0, 300.0]))
    limit = int((30 + 5 + 1) * RATE)  # window + search region + one read block
    assert _peak_buffer(short) == _peak_buffer(long)
    assert _peak_buffer(long) <= limit + RATE // 50


def test_peak_allocations_stay_small_for_a_long_chapter(tmp_path: Path) -> None:
    import tracemalloc

    wav = _write(tmp_path / "ten.wav", _speechlike(600, quiet_at=[27.0, 300.0]))
    whole_file_bytes = 600 * RATE * 4  # float32 samples, if the chapter were read whole
    tracemalloc.start()
    try:
        for _piece in iter_windows(wav):
            pass
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < whole_file_bytes / 4


@pytest.mark.skipif(not os.path.isdir("/proc/self/fd"), reason="needs /proc to count open files")
def test_stopping_early_releases_the_decoded_file(tmp_path: Path) -> None:
    wav = _write(tmp_path / "long.wav", _speechlike(120, quiet_at=[27.0]))

    def open_files() -> int:
        return len(os.listdir("/proc/self/fd"))

    before = open_files()
    windows_seen = iter_windows(wav)
    next(windows_seen)
    assert open_files() > before  # the file is open while windows are read
    windows_seen.close()
    assert open_files() == before
