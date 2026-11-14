"""Real CLI output matches the desktop app's contracts in desktop/contracts (Tauri D9.c, TD4.02).

Every output the app reads is produced here by the real CLI code, offline: a fake Kitten
voice stands in for synthesis and a stand-in server for the review page.
"""

from __future__ import annotations

import json
import shutil
import sys
import types
from pathlib import Path
from typing import Any

import fitz
import jsonschema
import numpy as np
import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.models import BookManifest, Chapter, CleanupEdit, DocumentBlock
from pdf2audiobook.workspace import write_manifest

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "desktop" / "contracts"
runner = CliRunner()


def _check(schema: str, payload: Any) -> None:
    contract = json.loads((CONTRACTS / f"{schema}.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(contract)
    validator = jsonschema.Draft202012Validator(contract, format_checker=jsonschema.FormatChecker())
    validator.validate(payload)


def _ok(*args: str) -> Any:
    result = runner.invoke(app, ["--no-progress", *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _book(path: Path) -> Path:
    pdf = fitz.open()
    for index in range(2):
        page = pdf.new_page()
        page.insert_text((80, 60), f"Chapter {index + 1}")
        page.insert_text((80, 115), f"Test sentence from chapter {index + 1}.")
    pdf.save(path)
    pdf.close()
    return path


class _FakeKitten:
    sample_rate = 24000
    supports_voice_listing = True
    max_chars_per_chunk = 350

    def __init__(self, model: str) -> None:
        self.model = model

    def list_voices(self) -> list[str]:
        return ["Jasper", "Luna"]

    def generate(self, text: str, *, voice: str, speed: float) -> np.ndarray:
        return np.ones(2400, dtype=np.float32) * 0.03


@pytest.fixture
def book(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    monkeypatch.setattr("pdf2audiobook.pipeline.KittenProvider", _FakeKitten)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-config"))
    source = _book(tmp_path / "book.pdf")
    output = tmp_path / "out"
    manifest = Path(
        _ok(
            "analyze", str(source), "--no-llm", "--ocr", "never", "--output", str(output), "--json"
        )["manifest"]
    )
    return {"source": source, "output": output, "manifest": manifest}


def test_doctor() -> None:
    _check("doctor", _ok("doctor", "--no-config", "--json"))


def test_config_show() -> None:
    _check("config-show", _ok("config", "show", "--no-config", "--sources", "--json"))


def test_inspect_book(book: dict[str, Path]) -> None:
    _check("inspect-book", _ok("inspect", str(book["source"]), "--json"))


def test_inspect_manifest(book: dict[str, Path]) -> None:
    _check("inspect-manifest", _ok("inspect", str(book["manifest"]), "--json"))


def test_workspace(book: dict[str, Path]) -> None:
    payload = _ok("workspace", str(book["source"]), "--output", str(book["output"]), "--json")
    _check("workspace", payload)
    assert payload["exists"] is True


def test_voices(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.ModuleType("kittenml")
    fake.KittenTTS = type(  # type: ignore[attr-defined]
        "KittenTTS", (), {"__init__": lambda self, _m: None, "available_voices": ["Jasper"]}
    )
    monkeypatch.setitem(sys.modules, "kittenml", fake)
    _check("voices", _ok("voices", "--no-config", "--json"))


def test_thumbnail(book: dict[str, Path], tmp_path: Path) -> None:
    payload = _ok("thumbnail", str(book["source"]), "--output", str(tmp_path / "t.png"), "--json")
    _check("thumbnail", payload)


def test_analyze(book: dict[str, Path]) -> None:
    # The fixture already ran analyze; running it again resumes and reports the same shape.
    payload = _ok(
        "analyze", str(book["source"]), "--no-llm", "--ocr", "never",
        "--output", str(book["output"]), "--json",
    )  # fmt: skip
    _check("analyze", payload)


def test_run_status(book: dict[str, Path]) -> None:
    status = json.loads((book["manifest"].parent / "reports" / "run_status.json").read_text())
    _check("run-status", status)
    assert status["state"] == "completed"


def test_convert_dry_run(book: dict[str, Path]) -> None:
    payload = _ok(
        "convert", str(book["source"]), "--no-llm", "--ocr", "never",
        "--output", str(book["output"]), "--dry-run", "--json",
    )  # fmt: skip
    _check("convert-dry-run", payload)


def test_convert_and_pack_m4b(book: dict[str, Path], tmp_path: Path) -> None:
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg not installed")
    converted = _ok(
        "convert", str(book["source"]), "--no-llm", "--ocr", "never",
        "--output", str(book["output"]), "--json",
    )  # fmt: skip
    _check("convert", converted)
    assert len(converted["mp3_files"]) == 2
    packed = _ok(
        "pack-m4b", str(book["manifest"]), "--output", str(tmp_path / "book.m4b"), "--json"
    )
    _check("pack-m4b", packed)
    _check("inspect-manifest", _ok("inspect", str(book["manifest"]), "--json"))


def test_edits_list(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    write_manifest(
        path,
        BookManifest(
            schema_version=3,
            input_sha256="x",
            title="Book",
            source_path="source.pdf",
            blocks=[DocumentBlock(id="b0", text="Teh text.", page_index=0)],
            chapters=[
                Chapter(id="a", number=1, title="One", start_block=0, end_block=1, confidence=1)
            ],
            edits=[
                CleanupEdit(
                    block_id="b0",
                    original="Teh text.",
                    replacement="The text.",
                    reason="spelling",
                    confidence=0.9,
                    accepted=False,
                    provider="ollama",
                )
            ],
        ),
    )
    payload = _ok("edits", "list", str(path), "--status", "all", "--json")
    _check("edits-list", payload)
    assert [edit["status"] for edit in payload["edits"]] == ["pending"]


def test_review_address(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Server:
        server_address = ("127.0.0.1", 43210)

        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            pass

    monkeypatch.setattr("pdf2audiobook.review_ui.create_review_server", lambda *_a, **_k: Server())
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    result = runner.invoke(app, ["review", str(manifest), "--json"])
    assert result.exit_code == 0, result.output
    _check("review-address", json.loads(result.stdout.splitlines()[0]))


def test_error_with_and_without_a_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = runner.invoke(app, ["workspace", str(tmp_path / "missing.pdf"), "--json"])
    assert missing.exit_code == 3
    _check("error", json.loads(missing.stderr.splitlines()[-1]))

    path = tmp_path / "manifest.json"
    write_manifest(
        path,
        BookManifest(
            schema_version=3,
            input_sha256="x",
            title="Book",
            source_path="source.pdf",
            blocks=[DocumentBlock(id="b0", text="Text.", page_index=0)],
            chapters=[
                Chapter(id="a", number=1, title="One", start_block=0, end_block=1, confidence=0.5)
            ],
        ),
    )
    source = tmp_path / "source.pdf"
    source.write_bytes(b"synthetic")
    monkeypatch.setattr("pdf2audiobook.pipeline.analyze_book", lambda *_a, **_k: path)
    gated = runner.invoke(app, ["convert", str(source), "--no-config", "--dry-run", "--json"])
    assert gated.exit_code == 6
    error = json.loads(gated.stderr.splitlines()[-1])
    _check("error", error)
    assert error["error"]["reason"] == "review_required"


def test_every_contract_has_a_test() -> None:
    contracts = {path.name.removesuffix(".schema.json") for path in CONTRACTS.glob("*.schema.json")}
    tested = {
        "doctor", "config-show", "inspect-book", "inspect-manifest", "workspace", "voices",
        "thumbnail", "analyze", "run-status", "convert-dry-run", "convert", "pack-m4b",
        "edits-list", "review-address", "error",
    }  # fmt: skip
    assert contracts == tested
