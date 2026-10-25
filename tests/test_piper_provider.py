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
