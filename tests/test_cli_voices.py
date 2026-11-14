"""`pdf2audiobook voices` lists the selected provider's voices (Tauri spec D2.e)."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.tts import KittenProvider

runner = CliRunner()


class _FakeKittenModel:
    available_voices = ["Bella", "Jasper", "Luna"]

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    def generate(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("listing voices must not synthesize")


@pytest.fixture
def fake_kittenml(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("kittenml")
    module.KittenTTS = _FakeKittenModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "kittenml", module)


def _voices(*args: str) -> object:
    return runner.invoke(app, ["voices", "--no-config", "--json", *args])


@pytest.mark.usefixtures("fake_kittenml")
def test_kitten_voices_match_the_provider_listing() -> None:
    result = _voices()

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == {
        "provider": "kitten",
        "voices": KittenProvider("mini").list_voices(),
        "listable": True,
        "default_voice": "Jasper",
        "warnings": [],
    }
    assert payload["voices"] == ["Bella", "Jasper", "Luna"]


@pytest.mark.usefixtures("fake_kittenml")
def test_tts_model_selects_the_kitten_model(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded: list[str] = []

    class Recording(_FakeKittenModel):
        def __init__(self, model_id: str) -> None:
            loaded.append(model_id)

    monkeypatch.setattr(sys.modules["kittenml"], "KittenTTS", Recording)

    result = _voices("--tts-provider", "kitten", "--tts-model", "nano")

    assert result.exit_code == 0, result.output
    assert loaded == ["KittenML/kitten-tts-nano-0.8"]


def test_piper_reports_that_its_speakers_cannot_be_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = tmp_path / "private-voice.onnx"
    model.write_bytes(b"onnx")
    Path(f"{model}.json").write_text(json.dumps({"audio": {"sample_rate": 22050}}))
    monkeypatch.setattr("pdf2audiobook.tts.shutil.which", lambda _name: "/usr/bin/piper")

    result = _voices("--tts-provider", "piper", "--tts-model", str(model))

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "provider": "piper",
        "voices": [],
        "listable": False,
        "default_voice": "",
        "warnings": [],
    }
    assert str(tmp_path) not in result.stdout


def test_missing_kitten_gives_the_existing_install_message(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "kittenml", None)  # import raises ImportError

    result = _voices()

    assert result.exit_code == 6
    assert json.loads(result.stderr)["error"] == {
        "type": "AudioError",
        "code": 6,
        "message": "Kitten TTS is not installed. Run 'uv sync --extra kitten' first.",
    }


def test_missing_piper_model_gives_the_existing_message(tmp_path: Path) -> None:
    result = _voices("--tts-provider", "piper", "--tts-model", str(tmp_path / "secret.onnx"))

    assert result.exit_code == 6
    error = json.loads(result.stderr)["error"]
    assert error["message"] == "Piper model file is unavailable; configure a local ONNX voice model"
    assert "secret" not in result.stderr
