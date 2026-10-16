from pathlib import Path

import fitz
import pytest

from pdf2audiobook.config import Settings
from pdf2audiobook.document.structure import chapter_coverage_report
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.workspace import read_manifest, write_manifest


def _book(tmp_path: Path):
    source = tmp_path / "book.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((80, 80), "Chapter 1")
    page.insert_text((80, 120), "Original prose is protected.")
    doc.save(source)
    doc.close()
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.pdf.ocr = "never"
    settings.llm.enabled = False
    path = analyze_book(source, settings)
    return source, settings, path


def test_report_exact_coverage_and_accepted_replacements(tmp_path):
    source, settings, path = _book(tmp_path)
    manifest = read_manifest(path)
    report = chapter_coverage_report(manifest)
    assert report["valid"] is True
    assert report["covered_blocks"] == report["source_blocks"]
    assert (path.parent / "coverage.json").is_file()
    from pdf2audiobook.models import CleanupEdit

    original = manifest.blocks[1]
    manifest.edits.append(CleanupEdit(
        block_id=original.id, original=original.text,
        replacement="Corrected prose.", reason="manual verified correction",
        confidence=1, accepted=True, provider="human"
    ))
    write_manifest(path, manifest)
    analyze_book(source, settings)
    text = (path.parent / "chapters" / "001.txt").read_text()
    assert "Corrected prose." in text
    assert "Original prose" not in text
    assert read_manifest(path).blocks[1].text == original.text


@pytest.mark.parametrize("invalid", ["unknown", "mismatch", "duplicate"])
def test_invalid_cleanup_edit_rejected(tmp_path, invalid):
    source, settings, path = _book(tmp_path)
    manifest = read_manifest(path)
    from pdf2audiobook.models import CleanupEdit

    first = manifest.blocks[1]
    edit = CleanupEdit(
        block_id="unknown" if invalid == "unknown" else first.id,
        original="wrong original" if invalid == "mismatch" else first.text,
        replacement="", reason="test", confidence=1, accepted=True,
    )
    manifest.edits.append(edit)
    if invalid == "duplicate":
        manifest.edits.append(edit.model_copy())
    write_manifest(path, manifest)
    with pytest.raises(ExtractionError):
        analyze_book(source, settings)
