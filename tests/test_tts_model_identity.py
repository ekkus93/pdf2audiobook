"""Audio cache identities follow model content and stable absolute paths."""

from importlib.metadata import PackageNotFoundError
from pathlib import Path

import numpy as np
import pytest

from pdf2audiobook.audio import synthesize_chunks
from pdf2audiobook.config import Settings, TTSProfile
from pdf2audiobook.pipeline import _tts_model_identity
from pdf2audiobook.tts import selection
from pdf2audiobook.workspace import fingerprint


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


# --- Identity fallbacks and Piper profiles (test coverage spec T6.a) ----------


def _piper_settings(model_path):
    settings = Settings()
    settings.tts.provider = "piper"
    settings.tts.piper.model_path = model_path
    return settings


def test_piper_without_a_model_path_has_a_stable_placeholder_identity(tmp_path):
    """T6.a: no configured model gives one fixed identity, unlike any real model."""
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"model")

    missing = _tts_model_identity(_piper_settings(None))

    assert missing == _tts_model_identity(_piper_settings(""))
    assert missing != _tts_model_identity(_piper_settings(str(model)))


def test_piper_model_files_that_disappear_change_the_identity(tmp_path):
    """T6.a: a missing model or config file is recorded as missing, not skipped."""
    model = tmp_path / "voice.onnx"
    config = Path(f"{model}.json")
    model.write_bytes(b"model")
    config.write_text("{}")
    settings = _piper_settings(str(model))
    present = _tts_model_identity(settings)

    config.unlink()
    without_config = _tts_model_identity(settings)
    model.unlink()
    without_either = _tts_model_identity(settings)

    assert len({present, without_config, without_either}) == 3
    # Pinned: this value is a resume-cache identity, so its format must not drift.
    assert without_either == fingerprint(
        "piper-model-v1", str(model.resolve()), [(".onnx", "missing"), (".json", "missing")]
    )


def test_kitten_identity_records_a_missing_engine(monkeypatch):
    """T6.a: without kittenml installed the identity still exists and differs."""
    installed = _tts_model_identity(Settings())

    def not_installed(_name):
        raise PackageNotFoundError("kittenml")

    monkeypatch.setattr(selection, "package_version", not_installed)

    assert _tts_model_identity(Settings()) != installed
    assert _tts_model_identity(Settings()) == _tts_model_identity(Settings())


def _profiled(profile, provider="kitten"):
    settings = Settings()
    settings.tts.provider = provider
    settings.tts.profiles = {"book": profile}
    return settings


def test_piper_profile_sets_the_piper_voice_speed_and_model():
    """T6.a: a Piper profile writes Piper's own fields, not Kitten's."""
    settings = _profiled(
        TTSProfile(provider="piper", piper_model_path="/models/v.onnx", voice="3", speed=1.4)
    )
    kitten_before = settings.tts.kitten.model_copy()

    selected = selection.settings_for_book_tts(settings, "book")

    assert selected.tts.provider == "piper"
    assert selected.tts.piper.model_path == "/models/v.onnx"
    assert selected.tts.piper.voice == "3"
    assert selected.tts.piper.speed == 1.4
    assert selected.tts.kitten == kitten_before
    assert settings.tts.provider == "kitten"  # the original settings are untouched


@pytest.mark.parametrize("option", ["tts_provider", "tts_model", "voice", "speed"])
def test_explicit_option_overrides_the_profile(option):
    """T6.a: a command-line option wins over the profile for that field only."""
    settings = _profiled(
        TTSProfile(provider="piper", piper_model_path="/models/v.onnx", voice="3", speed=1.4),
        provider="piper",
    )
    original = settings.tts.piper.model_copy()

    selected = selection.settings_for_book_tts(settings, "book", explicit=frozenset({option}))

    fields = {
        "tts_model": ("model_path", "/models/v.onnx"),
        "voice": ("voice", "3"),
        "speed": ("speed", 1.4),
    }
    for name, (field, profile_value) in fields.items():
        expected = getattr(original, field) if name == option else profile_value
        assert getattr(selected.tts.piper, field) == expected


def test_book_without_a_profile_keeps_the_same_settings_object():
    """T6.a: no profile for this book means no copy and no change."""
    settings = _profiled(TTSProfile(voice="Bella"))

    assert selection.settings_for_book_tts(settings, "other-book") is settings


def test_explicit_provider_overrides_the_profile_provider():
    """T6.a: --tts-provider keeps the configured provider even when the profile names another."""
    settings = _profiled(TTSProfile(provider="piper"), provider="kitten")

    assert selection.settings_for_book_tts(settings, "book").tts.provider == "piper"
    assert (
        selection.settings_for_book_tts(
            settings, "book", explicit=frozenset({"tts_provider"})
        ).tts.provider
        == "kitten"
    )
