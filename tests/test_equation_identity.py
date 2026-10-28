"""Equation processing enters the analysis identity only when it is on (C5)."""

import json
import re
from pathlib import Path
from typing import Any

import fitz
import pytest

from pdf2audiobook import pipeline
from pdf2audiobook.config import Settings
from pdf2audiobook.pipeline import _analysis_stage_fingerprints, analyze_book
from pdf2audiobook.workspace import read_manifest, write_manifest

# Computed from the code as it was before equation processing existed.
GOLDEN = {
    "extraction": "db2c8c85be9eb7d708f6885142d3eb8793c6f6c73ae01acb5277153eccdaf29b",
    "chapter-boundaries": "b452f3c85d651719242df88e15ade6f3793837d1b1675d2c6eb589389c447795",
    "llm-analysis": "957aaebace1e9521bc8bc48912039c98866995432d32f5a26c8f9b3caeaa3ac8",
}
GOLDEN_LLM_DISABLED = "9982c77107fc84c3a01ffcc418fc63bcfc463fc1806f5642ef9ef912679d5773"


def test_stage_fingerprints_are_unchanged_by_either_reading_setting() -> None:
    assert _analysis_stage_fingerprints("a" * 64, Settings(), None) == GOLDEN
    for citations in (False, True):
        for equations in (False, True):
            settings = Settings()
            settings.reading.process_citations = citations
            settings.reading.process_equations = equations
            assert _analysis_stage_fingerprints("a" * 64, settings, None) == GOLDEN
    disabled = Settings()
    disabled.llm.enabled = False
    assert _analysis_stage_fingerprints("a" * 64, disabled, None)["llm-analysis"] == (
        GOLDEN_LLM_DISABLED
    )


class Model:
    """Answers structure and equation requests, and counts each kind."""

    structure = 0
    equations = 0

    def __enter__(self) -> "Model":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def complete_json(self, *, instructions: str, document_text: str) -> dict[str, Any]:
        if "mathematical notation" in instructions:
            type(self).equations += 1
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
        type(self).structure += 1
        return {"headings": []}


@pytest.fixture(autouse=True)
def model(monkeypatch: pytest.MonkeyPatch) -> type[Model]:
    Model.structure = Model.equations = 0
    monkeypatch.setattr(pipeline, "create_provider", lambda _settings, **_kw: Model())
    return Model


def _book(tmp_path: Path) -> tuple[Path, Settings]:
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
    llm.structure = True
    llm.contents = llm.cleanup = llm.classification = llm.narration = llm.vision = False
    return source, settings


def test_an_approved_workspace_is_not_refused_when_the_setting_differs(
    tmp_path: Path, model: type[Model]
) -> None:
    source, settings = _book(tmp_path)
    settings.reading.process_equations = False
    path = analyze_book(source, settings)
    manifest = read_manifest(path)
    manifest.chapters[0].manually_approved = True
    write_manifest(path, manifest)
    settings.reading.process_equations = True
    assert analyze_book(source, settings) == path  # resumed as is, no refusal
    assert model.equations == 0


def test_the_setting_on_proposes_pending_equation_edits(tmp_path: Path, model: type[Model]) -> None:
    source, settings = _book(tmp_path)
    settings.reading.process_equations = True
    manifest = read_manifest(analyze_book(source, settings))
    pending = [e for e in manifest.edits if e.provider == "llm"]
    assert [e.original for e in pending] == ["h1 = 8", "h2 = 9"]
    assert not any(e.accepted for e in pending)
