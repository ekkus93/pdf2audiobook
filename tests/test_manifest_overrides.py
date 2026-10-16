from pathlib import Path

import fitz
import pytest

from pdf2audiobook.config import Settings
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.workspace import read_manifest, write_manifest


def test_manual_manifest_is_authoritative(tmp_path: Path):
    source = tmp_path / "chapters.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((80, 80), "Chapter 1")
    page.insert_text((80, 130), "First sentence.")
    page.insert_text((80, 180), "Chapter 2")
    page.insert_text((80, 230), "Second sentence.")
    document.save(source)
    document.close()
    settings = Settings()
    settings.pdf.ocr = "never"
    settings.llm.enabled = False
    settings.general.output_dir = str(tmp_path / "out")

    manifest_file = analyze_book(source, settings)
    manifest = read_manifest(manifest_file)
    assert len(manifest.chapters) == 2

    # Move the second boundary to include the last line of chapter one.
    manifest.chapters[0].end_block = 3
    manifest.chapters[1].start_block = 3
    manifest.chapters[0].manually_approved = True
    write_manifest(manifest_file, manifest)
    analyze_book(source, settings)
    new_first = (manifest_file.parent / "chapters" / "001.txt").read_text()
    new_second = (manifest_file.parent / "chapters" / "002.txt").read_text()
    assert "Chapter 2" in new_first
    assert "Chapter 2" not in new_second

    manifest.chapters[1].start_block = 2
    write_manifest(manifest_file, manifest)
    with pytest.raises(ExtractionError, match="overlaps"):
        analyze_book(source, settings)
