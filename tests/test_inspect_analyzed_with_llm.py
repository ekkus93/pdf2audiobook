"""`inspect MANIFEST --json` says whether the last analysis used the LLM (desktop book options)."""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app

runner = CliRunner()


@pytest.fixture
def manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-config"))
    source = tmp_path / "book.pdf"
    pdf = fitz.open()
    for index in range(2):
        page = pdf.new_page()
        page.insert_text((80, 60), f"Chapter {index + 1}")
        page.insert_text((80, 115), f"Sentence {index + 1}.")
    pdf.save(source)
    pdf.close()
    result = runner.invoke(
        app,
        [
            "analyze",
            str(source),
            "--no-llm",
            "--ocr",
            "never",
            "--output",
            str(tmp_path / "out"),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    return Path(json.loads(result.stdout)["manifest"])


def _inspect(manifest: Path) -> object:
    result = runner.invoke(app, ["inspect", str(manifest), "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)["analyzed_with_llm"]


def test_an_analysis_without_the_llm_says_so(manifest: Path) -> None:
    assert _inspect(manifest) is False


def test_an_analysis_with_the_llm_says_so(manifest: Path) -> None:
    path = manifest.parent / "reports" / "analysis_fingerprints.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["stages"]["llm-analysis"] = "0" * 64
    path.write_text(json.dumps(record), encoding="utf-8")
    assert _inspect(manifest) is True


@pytest.mark.parametrize("content", [None, "not json", '{"stages": []}', '{"stages": {}}'])
def test_unknown_when_the_record_is_missing_or_unreadable(
    manifest: Path, content: str | None
) -> None:
    path = manifest.parent / "reports" / "analysis_fingerprints.json"
    if content is None:
        path.unlink()
    else:
        path.write_text(content, encoding="utf-8")
    assert _inspect(manifest) is None
