"""The temperature is part of Kitten 2 audio identity and of nothing else (spec K3)."""

import json
import shutil
from pathlib import Path

import fitz
import numpy as np
import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.config import Settings
from pdf2audiobook.tts.selection import _tts_model_identity

runner = CliRunner()


def _settings(model: str, temperature: float, provider: str = "kitten") -> Settings:
    return Settings.model_validate(
        {"tts": {"provider": provider, "kitten": {"model": model, "temperature": temperature}}}
    )


def test_the_kitten_2_model_identity_includes_the_temperature() -> None:
    from pdf2audiobook.tts.cloning import GENERATION
    from pdf2audiobook.workspace import fingerprint

    # Audio made before the setting existed was keyed by this identity, and is regenerated.
    assert _tts_model_identity(_settings("kitten2", 0.3)) != fingerprint(
        "kitten2-model-v1", GENERATION
    )
    assert _tts_model_identity(_settings("kitten2", 0.3)) != _tts_model_identity(
        _settings("kitten2", 0.2)
    )
    assert _tts_model_identity(_settings("KittenML/kitten-tts-2", 0.3)) == _tts_model_identity(
        _settings("kitten2", 0.3)
    )


@pytest.mark.parametrize("model", ["mini", "nano"])
def test_kitten_0_8_identities_ignore_the_temperature(model: str) -> None:
    assert _tts_model_identity(_settings(model, 0.3)) == _tts_model_identity(_settings(model, 0.2))


@pytest.fixture
def book(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg not installed")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    source = tmp_path / "book.pdf"
    with fitz.open() as pdf:
        for n in (1, 2):
            page = pdf.new_page()
            page.insert_text((80, 60), f"Chapter {n}")
            page.insert_text((80, 115), f"Book narration for chapter {n}. Another one follows.")
        pdf.save(source)
    calls: list[tuple[str, float | None]] = []

    def fake(temperature: float | None):
        class Voice:
            sample_rate = 24000
            max_chars_per_chunk = 350
            supports_voice_listing = True

            def generate(self, text: str, *, voice: str, speed: float) -> np.ndarray:
                calls.append((text, temperature))
                return np.ones(2400, dtype=np.float32) * 0.03

            def close(self) -> None:
                pass

        return Voice()

    monkeypatch.setattr(
        "pdf2audiobook.tts.clone_provider.Kitten2BuiltinProvider",
        lambda *, temperature: fake(temperature),
    )
    monkeypatch.setattr("pdf2audiobook.pipeline.KittenProvider", lambda model: fake(None))
    monkeypatch.setattr("pdf2audiobook.tts.catalog.require_model", lambda: None)
    output = tmp_path / "out"

    def convert(*args: str) -> None:
        result = runner.invoke(
            app,
            [
                "convert", str(source), "--no-llm", "--ocr", "never", "--output", str(output),
                *args, "--json",
            ],
        )  # fmt: skip
        assert result.exit_code == 0, result.output

    return {"convert": convert, "calls": calls, "output": output}


def _manifest_bytes(output: Path) -> bytes:
    return next(output.glob("*/manifest.json")).read_bytes()


def test_kitten_2_regenerates_only_when_the_temperature_changes(book: dict) -> None:
    convert, calls = book["convert"], book["calls"]
    convert("--tts-model", "kitten2")
    first = len(calls)
    assert first > 0 and {temperature for _text, temperature in calls} == {0.3}
    manifest = _manifest_bytes(book["output"])

    convert("--tts-model", "kitten2", "--tts-temperature", "0.3")
    assert len(calls) == first

    convert("--tts-model", "kitten2", "--tts-temperature", "0.2")
    assert len(calls) == 2 * first
    assert {temperature for _text, temperature in calls[first:]} == {0.2}
    assert _manifest_bytes(book["output"]) == manifest


def test_kitten_0_8_audio_is_kept_when_the_temperature_changes(book: dict) -> None:
    convert, calls = book["convert"], book["calls"]
    convert()
    first = len(calls)
    assert first > 0
    convert("--tts-temperature", "0.2")
    assert len(calls) == first


def test_a_sidecar_recorded_before_the_temperature_existed_is_not_reused(book: dict) -> None:
    convert = book["convert"]
    convert("--tts-model", "kitten2")
    sidecars = list(book["output"].glob("*/audio/*.cache.json"))
    assert sidecars
    for sidecar in sidecars:
        record = json.loads(sidecar.read_text())
        assert record["rendering_inputs"]["kitten2_temperature"] == 0.3
        del record["rendering_inputs"]["kitten2_temperature"]
        sidecar.write_text(json.dumps(record))
    convert("--tts-model", "kitten2")
    # The chapter MP3 is rebuilt, from chunk audio cached at the same temperature.
    for sidecar in sidecars:
        assert json.loads(sidecar.read_text())["rendering_inputs"]["kitten2_temperature"] == 0.3
