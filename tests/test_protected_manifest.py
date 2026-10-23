"""Approved manifest edits must survive cached analysis and reject destructive reruns."""

from pathlib import Path

import fitz
import pytest

from pdf2audiobook.config import Settings
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.workspace import read_manifest, write_manifest


def test_approved_chapter_manifest_not_silently_overwritten(tmp_path: Path):
    source = tmp_path / "example.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((80, 70), "Chapter 1")
    page.insert_text((80, 140), "Some source material.")
    document.save(source)
    document.close()

    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.llm.enabled = False
    settings.pdf.ocr = "never"
    manifest_path = analyze_book(source, settings)
    manifest = read_manifest(manifest_path)
    manifest.chapters[0].manually_approved = True
    write_manifest(manifest_path, manifest)

    # Repair derived chapter text instead of discarding approved decisions.
    transcript = manifest_path.parent / "chapters" / "001.txt"
    transcript.unlink()
    analyze_book(source, settings)
    assert transcript.is_file()
    assert read_manifest(manifest_path).chapters[0].manually_approved

    settings.general.resume = False
    with pytest.raises(ExtractionError, match="manually approved"):
        analyze_book(source, settings)
    assert read_manifest(manifest_path).chapters[0].manually_approved

    settings.general.resume = True
    settings.pdf.ocr_dpi = 320
    with pytest.raises(ExtractionError, match="manually approved"):
        analyze_book(source, settings)
    assert read_manifest(manifest_path).chapters[0].manually_approved
