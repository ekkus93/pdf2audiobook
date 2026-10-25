"""Audio cache identities follow model content and stable absolute paths."""

from pathlib import Path

import numpy as np

from pdf2audiobook.audio import synthesize_chunks
from pdf2audiobook.config import Settings
from pdf2audiobook.pipeline import _tts_model_identity


class Provider:
    sample_rate = 24000
    max_chars_per_chunk = 350

    def __init__(self):
        self.calls = 0

    def generate(self, text, *, voice, speed):
        self.calls += 1
        return np.full(24, 0.1, dtype=np.float32)


def test_piper_model_bytes_change_mp3_and_wav_identities(tmp_path: Path):
    model = tmp_path / "voice.onnx"
    config = Path(f"{model}.json")
    model.write_bytes(b"model-one")
    config.write_text('{"audio":{"sample_rate":24000}}')
    settings = Settings()
    settings.tts.provider = "piper"
    settings.tts.piper.model_path = str(model)
    first = _tts_model_identity(settings)
    provider = Provider()
    cache = tmp_path / "cache"
    synthesize_chunks(
        "A short sentence.", provider, model=first, voice="", speed=1, pause_ms=0, cache=cache
    )
    assert provider.calls == 1

    model.write_bytes(b"model-two")
    model.touch()
    second = _tts_model_identity(settings)
    assert second != first
    synthesize_chunks(
        "A short sentence.", provider, model=second, voice="", speed=1, pause_ms=0, cache=cache
    )
    assert provider.calls == 2


def test_relative_model_path_uses_stable_absolute_identity(tmp_path: Path, monkeypatch):
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"model")
    Path(f"{model}.json").write_text('{"audio":{"sample_rate":24000}}')
    settings = Settings()
    settings.tts.provider = "piper"
    monkeypatch.chdir(tmp_path)
    settings.tts.piper.model_path = "voice.onnx"
    relative_identity = _tts_model_identity(settings)
    settings.tts.piper.model_path = str(model.resolve())
    assert _tts_model_identity(settings) == relative_identity
