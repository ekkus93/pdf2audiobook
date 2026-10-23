"""Synthetic scanned/mixed-PDF integration acceptance (no copyrighted content)."""

from __future__ import annotations

import shutil
from pathlib import Path

import fitz
import pytest

from pdf2audiobook.config import Settings
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.workspace import read_manifest


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract not installed")
def test_mixed_embedded_and_scanned_text(tmp_path: Path):
    source = tmp_path / "mixed.pdf"
    scanned = fitz.open()
    p = scanned.new_page(width=400, height=300)
    p.insert_text((30, 60), "Chapter 1", fontsize=25)
    p.insert_text((30, 120), "The scanned story begins here.", fontsize=18)
    bitmap = p.get_pixmap(matrix=fitz.Matrix(2, 2))
    scanned.close()

    book = fitz.open()
    first = book.new_page(width=400, height=300)
    first.insert_image(first.rect, pixmap=bitmap)
    next_page = book.new_page(width=400, height=300)
    next_page.insert_text((30, 60), "Chapter 2", fontsize=25)
    next_page.insert_text((30, 120), "The embedded story continues here.", fontsize=18)
    book.save(source)
    book.close()

    settings = Settings()
    settings.pdf.ocr = "auto"
    settings.llm.enabled = False
    settings.general.output_dir = str(tmp_path / "output")
    manifest = read_manifest(analyze_book(source, settings))
    assert len(manifest.chapters) == 2
    assert any(span.origin == "ocr" and span.page_index == 0 for span in manifest.spans)
    assert any(span.origin == "embedded" and span.page_index == 1 for span in manifest.spans)
    assert "scanned story" in " ".join(s.text.lower() for s in manifest.spans)
