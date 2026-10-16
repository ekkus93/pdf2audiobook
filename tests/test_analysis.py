from pathlib import Path

import fitz
import pytest

from pdf2audiobook.config import Settings
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.workspace import read_manifest


def test_end_to_end_text_pdf(tmp_path: Path):
    pdf_file = tmp_path / "sample.pdf"
    pdf = fitz.open()
    for index in range(3):
        page = pdf.new_page()
        page.insert_text((70, 70), f"Chapter {index + 1}")
        page.insert_text((70, 120), f"Story line {index + 1} with enough readable text.")
        page.insert_text((300, 810), str(index + 1))
    pdf.save(pdf_file)
    pdf.close()
    cfg = Settings()
    cfg.general.output_dir = str(tmp_path / "audio")
    cfg.pdf.ocr = "never"
    cfg.llm.enabled = False
    manifest_file = analyze_book(pdf_file, cfg)
    book = read_manifest(manifest_file)
    assert len(book.chapters) == 3
    assert len(book.spans) >= 6
    assert all(block.span_ids for block in book.blocks)
    assert [c.title for c in book.chapters] == ["Chapter 1", "Chapter 2", "Chapter 3"]
    first_text = (manifest_file.parent / "chapters" / "001.txt").read_text()
    assert "Story line 1" in first_text
    assert "Story line 2" not in first_text
    assert first_text.splitlines()[-1] != "1"


def test_no_chapters_fails_unless_enabled(tmp_path: Path):
    pdf_file = tmp_path / "nochapter.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((80, 100), "Just body text with no chapter headings at all.")
    pdf.save(pdf_file)
    pdf.close()
    settings = Settings()
    settings.pdf.ocr = "never"
    settings.llm.enabled = False
    with pytest.raises(ExtractionError, match="No reliable"):
        analyze_book(pdf_file, settings)
    settings.chapters.allow_single_chapter = True
    settings.general.output_dir = str(tmp_path / "output")
    assert read_manifest(analyze_book(pdf_file, settings)).chapters[0].title == "Full Book"
