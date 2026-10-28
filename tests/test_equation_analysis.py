"""Equation readings flow through analysis as pending edits and never change narration (C3)."""

import json
import re
from pathlib import Path
from typing import Any

import fitz
import pytest
from typer.testing import CliRunner

from pdf2audiobook import pipeline
from pdf2audiobook.cli import app
from pdf2audiobook.config import Settings
from pdf2audiobook.errors import LLMError
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.workspace import read_manifest


class FakeModel:
    """Reads every line containing '=' aloud; counts how often it is created and used."""

    created = 0
    requests = 0
    fail = False

    def __enter__(self) -> "FakeModel":
        type(self).created += 1
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def complete_json(self, *, instructions: str, document_text: str) -> dict[str, Any]:
        type(self).requests += 1
        if type(self).fail:
            raise LLMError("provider failed")
        records = [r for r in json.loads(document_text) if not r.get("context_only")]
        return {
            "readings": [
                {
                    "block_id": r["id"],
                    "original": r["text"],
                    "spoken": re.sub(r"\s*=\s*", " equals ", r["text"]),
                    "confidence": 0.9,
                }
                for r in records
                if "=" in r["text"]
            ]
        }


@pytest.fixture(autouse=True)
def fake_model(monkeypatch: pytest.MonkeyPatch) -> type[FakeModel]:
    FakeModel.created = FakeModel.requests = 0
    FakeModel.fail = False
    monkeypatch.setattr(pipeline, "create_provider", lambda _settings, **_kw: FakeModel())
    return FakeModel


def _book(tmp_path: Path, *, equations: bool, fallback: bool = False) -> tuple[Path, Settings]:
    source = tmp_path / "book.pdf"
    document = fitz.open()
    for number in (1, 2):
        page = document.new_page()
        page.insert_text((72, 72), f"Chapter {number}", fontsize=24)
        page.insert_text((72, 120), f"Prose for part {number} of the book.", fontsize=11)
        page.insert_text((72, 160), f"h{number} = {number + 7}", fontsize=11)
    document.save(source)
    document.close()
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.pdf.ocr = "never"
    llm = settings.llm
    llm.structure = llm.contents = llm.cleanup = llm.classification = False
    llm.narration = llm.vision = False
    llm.fallback_to_deterministic = fallback
    settings.reading.process_equations = equations
    return source, settings


def _chapter_text(manifest_path: Path, number: int) -> str:
    return (manifest_path.parent / "chapters" / f"{number:03d}.txt").read_text(encoding="utf-8")


def test_readings_become_pending_edits_and_change_nothing_else(tmp_path: Path) -> None:
    source, settings = _book(tmp_path, equations=True)
    manifest_path = analyze_book(source, settings)
    manifest = read_manifest(manifest_path)
    edits = [e for e in manifest.edits if e.provider == "llm"]
    assert sorted(e.original for e in edits) == ["h1 = 8", "h2 = 9"]
    assert all(e.accepted is False and "mathematical" in e.reason for e in edits)
    assert "h1 = 8" in _chapter_text(manifest_path, 1)  # still the literal text
    assert "equals" not in _chapter_text(manifest_path, 1) + _chapter_text(manifest_path, 2)
    decisions = json.loads((manifest_path.parent / "reports" / "llm_decisions.json").read_text())
    equation = [d for d in decisions["decisions"] if d["task"] == "equation"]
    assert {d["reason_code"] for d in equation} == {"verified_reading"} and len(equation) == 2


def test_with_the_setting_off_the_model_is_never_used(
    tmp_path: Path, fake_model: type[FakeModel]
) -> None:
    source, settings = _book(tmp_path, equations=False)
    manifest = read_manifest(analyze_book(source, settings))
    assert fake_model.created == 0 and fake_model.requests == 0
    assert manifest.edits == []


def test_a_model_failure_stops_analysis_unless_fallback_is_enabled(
    tmp_path: Path, fake_model: type[FakeModel]
) -> None:
    fake_model.fail = True
    source, settings = _book(tmp_path, equations=True)
    with pytest.raises(LLMError):
        analyze_book(source, settings)
    (tmp_path / "fallback").mkdir()
    source, settings = _book(tmp_path / "fallback", equations=True, fallback=True)
    manifest = read_manifest(analyze_book(source, settings))
    assert [e for e in manifest.edits if e.provider == "llm"] == []
    assert any("deterministic fallback" in w for w in manifest.warnings)


def test_a_proposed_reading_reaches_the_narration_only_once_accepted(tmp_path: Path) -> None:
    source, settings = _book(tmp_path, equations=True)
    manifest_path = analyze_book(source, settings)
    listed = CliRunner().invoke(app, ["edits", "list", str(manifest_path), "--json"])
    ids = [e["block_id"] for e in json.loads(listed.stdout)["edits"]]
    assert len(ids) == 2
    accepted = CliRunner().invoke(app, ["edits", "accept", str(manifest_path), ids[0], "--json"])
    assert accepted.exit_code == 0, accepted.stderr
    texts = _chapter_text(manifest_path, 1) + _chapter_text(manifest_path, 2)
    assert "h1 equals 8" in texts and "h2 = 9" in texts  # only the accepted one changed
