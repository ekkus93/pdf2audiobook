"""Contract tests for the optional external Piper voice adapter."""

import json
import wave

import numpy as np
import pytest

from pdf2audiobook.errors import AudioError
from pdf2audiobook.tts import PiperProvider


def _model(tmp_path):
    model = tmp_path / "voice.onnx"
    model.touch()
    model.with_name("voice.onnx.json").write_text(
        json.dumps({"audio": {"sample_rate": 22050}}), encoding="utf-8"
    )
    return model


def test_piper_reads_voice_rate_and_synthesizes_a_speaker(tmp_path, monkeypatch):
    model = _model(tmp_path)
    monkeypatch.setattr("pdf2audiobook.tts.shutil.which", lambda _: "/usr/bin/piper")
    calls = []

    def run(args, *, input, **kwargs):
        calls.append((args, input))
        target = args[args.index("--output_file") + 1]
        with wave.open(target, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(22050)
            wav.writeframes(np.asarray([0, 16384, -16384], dtype="<i2").tobytes())

    monkeypatch.setattr("pdf2audiobook.tts.subprocess.run", run)
    provider = PiperProvider(model)

    result = provider.generate("hello there", voice="2", speed=2)

    assert provider.sample_rate == 22050
    assert np.allclose(result, [0, 0.5, -0.5], atol=2e-5)
    args, text = calls[0]
    assert text == "hello there"
    assert args[args.index("--model") + 1] == str(model)
    assert args[args.index("--speaker") + 1] == "2"
    assert args[args.index("--length-scale") + 1] == "0.5"


def test_piper_suppresses_backend_diagnostics_that_may_contain_text(tmp_path, monkeypatch):
    import subprocess

    model = _model(tmp_path)
    monkeypatch.setattr("pdf2audiobook.tts.shutil.which", lambda _: "/usr/bin/piper")

    def failed(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], stderr="private narration")

    monkeypatch.setattr("pdf2audiobook.tts.subprocess.run", failed)
    provider = PiperProvider(model)

    with pytest.raises(AudioError, match="Piper speech generation failed") as exc:
        provider.generate("private narration", voice="", speed=1)
    assert "private narration" not in str(exc.value)


def test_piper_rejects_bad_voice_metadata_and_speed_before_subprocess(tmp_path, monkeypatch):
    model = tmp_path / "voice.onnx"
    model.touch()
    model.with_name("voice.onnx.json").write_text(
        json.dumps({"audio": {"sample_rate": True}}), encoding="utf-8"
    )
    monkeypatch.setattr("pdf2audiobook.tts.shutil.which", lambda _: "/usr/bin/piper")
    with pytest.raises(AudioError, match="sample rate"):
        PiperProvider(model)

    model.with_name("voice.onnx.json").write_text(
        json.dumps({"audio": {"sample_rate": 22050}}), encoding="utf-8"
    )
    provider = PiperProvider(model)
    with pytest.raises(AudioError, match="speech speed"):
        provider.generate("hello", voice="", speed=float("nan"))
    with pytest.raises(AudioError, match="speaker ID"):
        provider.generate("hello", voice="unknown", speed=1)


# --- Construction, input and output checks (test coverage round 2, U3) -------


@pytest.fixture
def piper(tmp_path, monkeypatch):
    """A model, a stand-in executable and a recording subprocess stand-in."""
    model = _model(tmp_path)
    monkeypatch.setattr("pdf2audiobook.tts.shutil.which", lambda _: "/usr/bin/piper")
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        raise AssertionError("Piper must not run")

    monkeypatch.setattr("pdf2audiobook.tts.subprocess.run", run)
    return model, calls


def test_missing_model_file_is_refused(tmp_path, monkeypatch):
    """U3.a: the ONNX model must be an existing file."""
    monkeypatch.setattr("pdf2audiobook.tts.shutil.which", lambda _: "/usr/bin/piper")

    for missing in (tmp_path / "absent.onnx", tmp_path):
        with pytest.raises(AudioError) as error:
            PiperProvider(missing)
        assert str(error.value) == (
            "Piper model file is unavailable; configure a local ONNX voice model"
        )
        assert str(tmp_path) not in str(error.value)


def test_missing_executable_is_refused(tmp_path, monkeypatch):
    """U3.a: the Piper CLI must be on PATH."""
    model = _model(tmp_path)
    monkeypatch.setattr("pdf2audiobook.tts.shutil.which", lambda _: None)

    with pytest.raises(AudioError) as error:
        PiperProvider(model)

    assert str(error.value) == "Piper CLI is unavailable; install piper-tts and check PATH"


_NO_RATE = "Piper voice configuration is missing a valid sample rate"
_BAD_RATE = "Piper voice sample rate must be an integer from 8000 to 192000"


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (None, _NO_RATE),
        (b"{not json", _NO_RATE),
        (b"[]", _NO_RATE),
        (json.dumps({"audio": {}}).encode(), _NO_RATE),
        (json.dumps({"audio": "22050"}).encode(), _NO_RATE),
        (b'{"audio": {"sample_rate": 22050}}' + b" " * (1_048_577 - 33), _NO_RATE),
        (json.dumps({"audio": {"sample_rate": 22050.0}}).encode(), _BAD_RATE),
        (json.dumps({"audio": {"sample_rate": "22050"}}).encode(), _BAD_RATE),
        (json.dumps({"audio": {"sample_rate": 7999}}).encode(), _BAD_RATE),
        (json.dumps({"audio": {"sample_rate": 192001}}).encode(), _BAD_RATE),
    ],
    ids=[
        "missing",
        "not-json",
        "not-an-object",
        "no-rate",
        "audio-not-an-object",
        "over-1-mib",
        "rate-float",
        "rate-string",
        "rate-too-low",
        "rate-too-high",
    ],
)
def test_invalid_voice_configuration_is_refused(tmp_path, monkeypatch, config, message):
    """U3.a: the voice config must be readable, small and give a supported rate."""
    model = tmp_path / "voice.onnx"
    model.touch()
    if config is not None:
        model.with_name("voice.onnx.json").write_bytes(config)
    monkeypatch.setattr("pdf2audiobook.tts.shutil.which", lambda _: "/usr/bin/piper")

    with pytest.raises(AudioError) as error:
        PiperProvider(model)

    assert str(error.value) == message


@pytest.mark.parametrize("size", [1_048_576])
def test_voice_configuration_at_the_size_limit_is_read(tmp_path, monkeypatch, size):
    """U3.a control: a config of exactly 1 MiB is accepted."""
    model = tmp_path / "voice.onnx"
    model.touch()
    body = b'{"audio": {"sample_rate": 8000}}'
    model.with_name("voice.onnx.json").write_bytes(body + b" " * (size - len(body)))
    monkeypatch.setattr("pdf2audiobook.tts.shutil.which", lambda _: "/usr/bin/piper")

    assert PiperProvider(model).sample_rate == 8000


_TEXT = "Piper text must be nonempty and within its chunk limit"
_SPEED = "Piper speech speed must be finite and in (0, 3]"
_SPEAKER = "Piper speaker ID must be a nonnegative integer"


@pytest.mark.parametrize(
    ("text", "voice", "speed", "message"),
    [
        ("", "", 1, _TEXT),
        ("   \n", "", 1, _TEXT),
        (None, "", 1, _TEXT),
        (b"hello", "", 1, _TEXT),
        ("x" * 351, "", 1, _TEXT),
        ("hello", "", True, _SPEED),
        ("hello", "", "1", _SPEED),
        ("hello", "", float("inf"), _SPEED),
        ("hello", "", 0, _SPEED),
        ("hello", "", -1, _SPEED),
        ("hello", "", 3.01, _SPEED),
        ("hello", "-1", 1, _SPEAKER),
        ("hello", "1.5", 1, _SPEAKER),
        ("hello", "1" * 11, 1, _SPEAKER),
        ("hello", 7, 1, _SPEAKER),
    ],
    ids=[
        "empty",
        "whitespace",
        "not-a-string",
        "bytes",
        "over-350",
        "speed-bool",
        "speed-string",
        "speed-infinite",
        "speed-zero",
        "speed-negative",
        "speed-over-3",
        "speaker-negative",
        "speaker-decimal-point",
        "speaker-11-digits",
        "speaker-not-a-string",
    ],
)
def test_invalid_input_is_refused_before_piper_runs(piper, text, voice, speed, message):
    """U3.b: every input check runs before the subprocess, with a fixed message."""
    model, calls = piper
    provider = PiperProvider(model)

    with pytest.raises(AudioError) as error:
        provider.generate(text, voice=voice, speed=speed)

    assert str(error.value) == message
    assert calls == []


def _wav_writer(*, rate=22050, channels=1, width=2, frames=b"\x00\x01" * 3):
    def write(path):
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(width)
            wav.setframerate(rate)
            wav.writeframes(frames)

    return write


def _header(frames_claimed, data):
    """A WAV whose data chunk claims more frames than it holds."""
    import struct

    size = frames_claimed * 2
    return (
        b"RIFF"
        + struct.pack("<I", 36 + size)
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, 22050, 44100, 2, 16)
        + b"data"
        + struct.pack("<I", size)
        + data
    )


def _sparse(path, size):
    with open(path, "wb") as stream:
        stream.truncate(size)


@pytest.mark.parametrize(
    ("write", "message"),
    [
        (None, "Piper returned missing or oversized audio"),
        (lambda p: _sparse(p, 128 * 1024 * 1024 + 1), "Piper returned missing or oversized audio"),
        (_wav_writer(rate=16000), "Piper returned unsupported audio format"),
        (_wav_writer(channels=2, frames=b"\x00" * 8), "Piper returned unsupported audio format"),
        (_wav_writer(width=1, frames=b"\x00" * 4), "Piper returned unsupported audio format"),
        (_wav_writer(frames=b""), "Piper returned empty or oversized audio"),
        (
            lambda p: p.write_bytes(_header(64 * 1024 * 1024 + 1, b"\x00\x00")),
            "Piper returned empty or oversized audio",
        ),
        (lambda p: p.write_bytes(_header(10, b"\x00\x00" * 2)), "Piper returned truncated audio"),
    ],
    ids=[
        "missing",
        "over-128-mib",
        "wrong-rate",
        "stereo",
        "8-bit",
        "no-frames",
        "over-64-mi-frames",
        "truncated",
    ],
)
def test_bad_piper_output_is_refused_and_cleaned_up(tmp_path, monkeypatch, write, message):
    """U3.c: Piper's WAV is checked before use; the temporary folder is removed."""
    from pathlib import Path

    model = _model(tmp_path)
    monkeypatch.setattr("pdf2audiobook.tts.shutil.which", lambda _: "/usr/bin/piper")
    outputs = []

    def run(args, **kwargs):
        output = Path(args[args.index("--output_file") + 1])
        outputs.append(output)
        if write is not None:
            write(output)

    monkeypatch.setattr("pdf2audiobook.tts.subprocess.run", run)

    with pytest.raises(AudioError) as error:
        PiperProvider(model).generate("hello", voice="", speed=1)

    assert str(error.value) == message
    assert len(outputs) == 1
    assert not outputs[0].parent.exists()


def test_piper_listing_and_health(tmp_path, monkeypatch):
    """U3.d: one model and no voice list; health needs both model and CLI."""
    model = _model(tmp_path)
    found = {"piper": "/usr/bin/piper"}
    monkeypatch.setattr("pdf2audiobook.tts.shutil.which", lambda name: found.get(name))
    provider = PiperProvider(model)

    assert provider.list_models() == [str(model)]
    assert provider.list_voices() == []
    assert provider.health() is True
    found.clear()
    assert provider.health() is False
    found["piper"] = "/usr/bin/piper"
    model.unlink()
    assert provider.health() is False
