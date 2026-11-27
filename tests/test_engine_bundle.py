"""The desktop app's bundled engine finds its own tools and data (self-contained app SC1, SC4)."""

import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pdf2audiobook import bundle
from pdf2audiobook.cli import app

runner = CliRunner()
ROOT = Path(__file__).resolve().parents[1]


def _bundle(tmp_path: Path, *, tessdata: bool = True, model: bool = True) -> Path:
    root = tmp_path / "engine"
    (root / "bin").mkdir(parents=True)
    (root / bundle.MARKER).write_text("{}", encoding="utf-8")
    if tessdata:
        data = root / "share" / "tessdata"
        data.mkdir(parents=True)
        (data / "eng.traineddata").write_bytes(b"synthetic")
        (data / "osd.traineddata").write_bytes(b"synthetic")
    if model:
        folder = root / "share" / "pdf2audiobook" / "models" / "kitten-tts-mini-0.8"
        folder.mkdir(parents=True)
        (folder / "config.json").write_text("{}", encoding="utf-8")
    return root


def test_outside_a_bundle_nothing_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    environ = {"PATH": "/usr/bin"}
    bundle.configure_environment(environ)
    assert environ == {"PATH": "/usr/bin"}
    assert bundle.bundled_model("KittenML/kitten-tts-mini-0.8") is None


def test_a_bundle_puts_its_tools_first_and_its_ocr_data_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _bundle(tmp_path)
    monkeypatch.setattr(sys, "prefix", str(root))
    environ = {"PATH": "/usr/bin"}
    bundle.configure_environment(environ)
    assert environ["PATH"] == f"{root / 'bin'}{os.pathsep}/usr/bin"
    assert environ["TESSDATA_PREFIX"] == str(root / "share" / "tessdata")
    bundle.configure_environment(environ)  # Idempotent.
    assert environ["PATH"].count(str(root / "bin")) == 1


def test_a_users_own_ocr_data_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "prefix", str(_bundle(tmp_path)))
    environ = {"PATH": "", "TESSDATA_PREFIX": "/mine"}
    bundle.configure_environment(environ)
    assert environ["TESSDATA_PREFIX"] == "/mine"


def test_the_bundled_model_folder_is_found_by_model_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _bundle(tmp_path)
    monkeypatch.setattr(sys, "prefix", str(root))
    expected = root / "share" / "pdf2audiobook" / "models" / "kitten-tts-mini-0.8"
    assert bundle.bundled_model("KittenML/kitten-tts-mini-0.8") == expected
    assert bundle.bundled_model("KittenML/kitten-tts-nano-0.8") is None
    assert bundle.bundled_model("../../etc") is None


def test_the_kitten_provider_loads_the_bundled_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _bundle(tmp_path)
    monkeypatch.setattr(sys, "prefix", str(root))
    loaded: list[str] = []

    class KittenTTS:
        def __init__(self, model: str) -> None:
            loaded.append(model)

    monkeypatch.setitem(sys.modules, "kittenml", types.SimpleNamespace(KittenTTS=KittenTTS))
    from pdf2audiobook.tts import KittenProvider

    provider = KittenProvider("mini")
    assert loaded == [str(root / "share" / "pdf2audiobook" / "models" / "kitten-tts-mini-0.8")]
    # The identity stays the model ID, so bundled and downloaded audio are interchangeable.
    assert provider.model_id == "KittenML/kitten-tts-mini-0.8"


def test_ocr_languages_come_from_the_data_directory_without_the_tesseract_program(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pdf2audiobook.pdf import tesseract_languages

    root = _bundle(tmp_path)
    monkeypatch.setenv("TESSDATA_PREFIX", str(root / "share" / "tessdata"))
    monkeypatch.setattr("pdf2audiobook.pdf_ocr.shutil.which", lambda name: None)
    assert tesseract_languages() == ["eng", "osd"]


def test_doctor_reports_ocr_ready_from_bundled_data_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _bundle(tmp_path)
    monkeypatch.setattr(sys, "prefix", str(root))
    monkeypatch.setenv("TESSDATA_PREFIX", "unset")
    monkeypatch.delenv("TESSDATA_PREFIX")
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    result = runner.invoke(app, ["doctor", "--no-config", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["tesseract"] is True
    assert payload["ocr_missing_languages"] == []
    assert str(tmp_path) not in result.stdout


def test_the_engine_runs_as_a_module() -> None:
    # The bundled engine is started through its interpreter: console-script shebangs
    # hold the build path and break when the app is moved.
    result = subprocess.run(
        [sys.executable, "-m", "pdf2audiobook", "--version"],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()
