"""One summary line instead of hundreds of identical ones (E4)."""

import json
from pathlib import Path

import pytest
from epub_book import write_novel_epub
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.config import Settings
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.workspace import read_manifest

LABEL = "could not read PDF page label"
SUMMARY = "EPUB pages have no printed page labels; physical page numbers are used"


@pytest.fixture(scope="module")
def epub(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("noise")
    return write_novel_epub(folder / "novel.epub", chapters=12)


def _args(source: Path, out: Path, *extra: str) -> list[str]:
    return ["analyze", str(source), "--no-config", "--no-llm", "--output", str(out), *extra]


def test_an_epub_has_one_label_summary_not_one_warning_per_page(epub: Path, tmp_path: Path) -> None:
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.llm.enabled = False
    manifest = read_manifest(analyze_book(epub, settings))
    assert not [w for w in manifest.warnings if LABEL in w]
    assert manifest.warnings.count(SUMMARY) == 1


def test_human_output_prints_one_review_line_with_the_warning_count(
    epub: Path, tmp_path: Path
) -> None:
    result = CliRunner().invoke(app, _args(epub, tmp_path / "out"))
    assert result.exit_code == 0, result.stderr
    lines = [line for line in result.stderr.splitlines() if "Book review is required" in line]
    assert len(lines) == 1
    manifest = read_manifest(next((tmp_path / "out").glob("*/manifest.json")))
    assert f"({len(manifest.warnings)} warnings in the manifest)" in lines[0]
    assert len(manifest.warnings) > 1


def test_json_output_lists_the_review_code_once_and_keeps_stderr_empty(
    epub: Path, tmp_path: Path
) -> None:
    result = CliRunner().invoke(app, _args(epub, tmp_path / "out", "--json"))
    assert result.exit_code == 0, result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout)["warnings"].count("review_warning") == 1


def test_a_book_with_no_warnings_prints_no_review_line(tmp_path: Path) -> None:
    import fitz

    source = tmp_path / "clean.pdf"
    doc = fitz.open()
    for number in (1, 2):
        page = doc.new_page()
        page.insert_text((72, 72), f"Chapter {number}", fontsize=24)
        page.insert_text((72, 120), "Plain words.", fontsize=11)
    doc.save(source)
    doc.close()
    result = CliRunner().invoke(app, _args(source, tmp_path / "out", "--ocr", "never"))
    assert result.exit_code == 0, result.stderr
    assert "Book review is required" not in result.stderr
