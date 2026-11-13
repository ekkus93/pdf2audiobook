"""Encoded MP3 output failures must not expose private document paths."""

import shutil
import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from pdf2audiobook import audio as audio_module
from pdf2audiobook.audio import encode_mp3, encoding
from pdf2audiobook.errors import AudioError


def _encode(target: Path) -> Path:
    return encode_mp3(
        np.full(2400, 0.05, dtype=np.float32),
        24000,
        target,
        bitrate="128k",
        target_rate=24000,
        title="Synthetic chapter",
        artist=None,
        album="Synthetic book",
        track=1,
    )


def test_mp3_directory_creation_error_redacts_private_path(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_module.shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    def fail_mkdir(_self, *args, **kwargs):
        raise OSError("PRIVATE_BOOK_DIRECTORY: disk access denied")

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)
    with pytest.raises(AudioError, match="Could not create MP3 output directory") as exc:
        _encode(tmp_path / "PRIVATE_BOOK_DIRECTORY" / "chapter.mp3")
    assert "PRIVATE_BOOK_DIRECTORY" not in str(exc.value)
    assert exc.value.__suppress_context__ is True


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
def test_mp3_publication_error_redacts_path_and_preserves_existing_file(tmp_path, monkeypatch):
    target = tmp_path / "PRIVATE_BOOK_TITLE.mp3"
    existing = b"existing completed audio placeholder"
    target.write_bytes(existing)

    def fail_replace(_self, _target):
        raise OSError("PRIVATE_BOOK_TITLE: cannot atomically replace output")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(AudioError, match="Could not publish encoded MP3") as exc:
        _encode(target)
    assert "PRIVATE_BOOK_TITLE" not in str(exc.value)
    assert exc.value.__suppress_context__ is True
    assert target.read_bytes() == existing


def test_mp3_temporary_workspace_error_redacts_private_path(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_module.shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    def fail_workspace(*, dir):
        raise OSError("PRIVATE_TEMP_DIRECTORY: cannot create workspace")

    monkeypatch.setattr(audio_module.tempfile, "TemporaryDirectory", fail_workspace)
    target = tmp_path / "PRIVATE_TEMP_DIRECTORY.mp3"
    with pytest.raises(AudioError, match="Could not manage temporary MP3 workspace") as exc:
        _encode(target)
    assert "PRIVATE_TEMP_DIRECTORY" not in str(exc.value)
    assert exc.value.__suppress_context__ is True
    assert not target.exists()


# --- Encoding validation and checks (test coverage spec T5) --------------------


class _FFmpeg:
    """Stands in for `encoding.subprocess`; records runs and can write the output."""

    PIPE = subprocess.PIPE
    TimeoutExpired = subprocess.TimeoutExpired

    def __init__(self, returncode=0, output=b"fake mp3"):
        self.calls = []
        self.returncode = returncode
        self.output = output

    def run(self, command, **_kwargs):
        self.calls.append(command)
        if self.output is not None:
            Path(command[-1]).write_bytes(self.output)
        return subprocess.CompletedProcess(command, self.returncode, b"", b"private stderr")


def _with_ffmpeg(monkeypatch, ffmpeg=None, *, installed=True):
    ffmpeg = ffmpeg or _FFmpeg()
    monkeypatch.setattr(encoding, "subprocess", ffmpeg)
    monkeypatch.setattr(
        encoding,
        "shutil",
        SimpleNamespace(
            which=lambda _name: "/usr/bin/ffmpeg" if installed else None,
            copyfile=shutil.copyfile,
        ),
    )
    return ffmpeg


def _encode_samples(target, samples, rate=24000):
    return encode_mp3(
        samples,
        rate,
        target,
        bitrate="128k",
        target_rate=24000,
        title="Synthetic chapter",
        artist=None,
        album="Synthetic book",
        track=1,
    )


@pytest.mark.parametrize(
    ("samples", "rate", "message"),
    [
        (np.ones(10, dtype=np.float32), 7999, "Audio sample_rate must be an integer"),
        (np.ones(10, dtype=np.float32), 192001, "Audio sample_rate must be an integer"),
        (np.ones(10, dtype=np.float32), 24000.0, "Audio sample_rate must be an integer"),
        (np.ones(10, dtype=np.float32), True, "Audio sample_rate must be an integer"),
        (["not", "audio"], 24000, "TTS returned invalid audio sample data"),
        (np.ones((2, 10), dtype=np.float32), 24000, "one-dimensional mono sample buffer"),
        (np.array([], dtype=np.float32), 24000, "TTS returned empty/nonfinite audio samples"),
        (np.array([0.1, np.nan], dtype=np.float32), 24000, "empty/nonfinite audio samples"),
    ],
    ids=[
        "rate-too-low",
        "rate-too-high",
        "rate-float",
        "rate-bool",
        "unconvertible",
        "stereo",
        "empty",
        "nan",
    ],
)
def test_invalid_audio_is_refused_before_ffmpeg_runs(tmp_path, monkeypatch, samples, rate, message):
    """T5.a: bad input never reaches FFmpeg and leaves no temporary WAV."""
    ffmpeg = _with_ffmpeg(monkeypatch)
    out = tmp_path / "out"

    with pytest.raises(AudioError, match=message):
        _encode_samples(out / "chapter.mp3", samples, rate)

    assert ffmpeg.calls == []
    assert list(out.iterdir()) == []


def test_missing_ffmpeg_stops_mp3_encoding_before_any_write(tmp_path, monkeypatch):
    """T5.b: without FFmpeg, encode_mp3 creates nothing."""
    _with_ffmpeg(monkeypatch, installed=False)

    with pytest.raises(AudioError, match="^FFmpeg executable not found in PATH$"):
        _encode_samples(tmp_path / "out" / "chapter.mp3", np.ones(10, dtype=np.float32))

    assert list(tmp_path.iterdir()) == []


def _wav(path, *, channels=1, rate=24000, frames=100):
    with wave.open(str(path), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\x00\x00" * channels * frames)
    return path


@pytest.mark.parametrize(
    "settings",
    [{"channels": 2}, {"rate": 16000}, {"frames": 0}],
    ids=["stereo", "wrong-rate", "no-frames"],
)
def test_chapter_wav_with_the_wrong_settings_is_refused(tmp_path, monkeypatch, settings):
    """T5.d: a prepared WAV must match the expected mono 16-bit format and rate."""
    ffmpeg = _with_ffmpeg(monkeypatch)
    source = _wav(tmp_path / "chapter.wav", **settings)

    with pytest.raises(AudioError, match="^Temporary chapter WAV has invalid audio settings$"):
        _encode_samples(tmp_path / "out" / "chapter.mp3", source)

    assert ffmpeg.calls == []


class _FakeMP3:
    """Stands in for mutagen's MP3: optional tags, a chosen duration."""

    saved: list[dict] = []

    def __init__(self, _path, ID3=None, *, tags=None, length=1.0):
        self.tags = tags
        self.info = SimpleNamespace(length=length)

    def add_tags(self):
        self.tags = {}

    def save(self):
        _FakeMP3.saved.append(dict(self.tags))


def test_mp3_without_tags_gets_new_tags_before_publication(tmp_path, monkeypatch):
    """T5.d: an encoder output with no ID3 tag is given one, then published."""
    _with_ffmpeg(monkeypatch)
    _FakeMP3.saved = []
    monkeypatch.setattr(encoding, "MP3", _FakeMP3)
    target = tmp_path / "out" / "chapter.mp3"

    assert _encode_samples(target, np.ones(10, dtype=np.float32)) == target

    assert _FakeMP3.saved == [
        {"title": "Synthetic chapter", "album": "Synthetic book", "tracknumber": "1"}
    ]
    assert target.read_bytes() == b"fake mp3"


def test_zero_duration_mp3_is_not_published(tmp_path, monkeypatch):
    """T5.d: an encoded MP3 with no audio is refused and nothing is published."""
    _with_ffmpeg(monkeypatch)
    monkeypatch.setattr(encoding, "MP3", lambda path, ID3=None: _FakeMP3(path, tags={}, length=0.0))
    target = tmp_path / "out" / "chapter.mp3"

    with pytest.raises(AudioError, match="^Encoded MP3 has zero duration$"):
        _encode_samples(target, np.ones(10, dtype=np.float32))

    assert list(target.parent.iterdir()) == []
