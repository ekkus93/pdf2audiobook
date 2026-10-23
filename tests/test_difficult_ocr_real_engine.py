"""Network-free, real-Tesseract regression for mixed and rotated raster pages.

The fixture is generated from synthetic text, not copyrighted book content.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import fitz
import pytest

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import _ocr_page_lines, extract_pdf


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract unavailable")
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_real_ocr_preserves_rotated_scan_and_mixed_page_provenance(
    tmp_path: Path,
    rotation: int,
):
    source = tmp_path / "rotated-mixed.pdf"
    raster_source = fitz.open()
    image_page = raster_source.new_page(width=595, height=842)
    image_page.insert_text((65, 100), "Chapter 1", fontsize=28)
    image_page.insert_text((65, 180), "Cedar lanterns illuminate the orchard.", fontsize=20)
    image_page.insert_text((65, 220), "Copper kettles echo through the valley.", fontsize=20)
    pixmap = image_page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    raster_source.close()

    book = fitz.open()
    scanned = book.new_page(width=595, height=842)
    scanned.insert_image(scanned.rect, pixmap=pixmap)
    scanned.set_rotation(rotation)
    embedded = book.new_page(width=595, height=842)
    embedded.insert_text((65, 100), "Chapter 2", fontsize=28)
    embedded.insert_text((65, 180), "Amber foxes gather at the river.", fontsize=20)
    book.save(source)
    book.close()

    settings = Pdf(ocr="auto", ocr_language="eng", ocr_dpi=300)
    result = extract_pdf(source, settings)
    by_page = [[span for span in result.spans if span.page_index == i] for i in range(2)]
    assert by_page[0] and by_page[1]
    assert all(span.origin == "ocr" for span in by_page[0])
    assert all(span.origin == "embedded" for span in by_page[1])
    scanned_text = " ".join(span.text for span in by_page[0]).casefold()
    embedded_text = " ".join(span.text for span in by_page[1]).casefold()
    assert "cedar lanterns" in scanned_text
    assert "copper kettles" in scanned_text
    assert "amber foxes" in embedded_text
    assert embedded_text.count("amber foxes") == 1
    assert all(span.bbox is not None for span in result.spans)
    assert result.page_sizes == [(595.0, 842.0), (595.0, 842.0)]


def test_ocr_restores_page_rotation_when_engine_fails(monkeypatch, tmp_path: Path):
    source = tmp_path / "ocr-failure.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.set_rotation(270)
    document.save(source)
    document.close()

    def broken_ocr(self, **kwargs):
        assert self.rotation == 0
        raise RuntimeError("synthetic OCR engine failure")

    monkeypatch.setattr(fitz.Page, "get_textpage_ocr", broken_ocr)
    with fitz.open(source) as document:
        page = document[0]
        assert page.rotation == 270
        with pytest.raises(RuntimeError, match="synthetic OCR engine failure"):
            _ocr_page_lines(page, Pdf(ocr="always"))
        assert page.rotation == 270
    with fitz.open(source) as document:
        assert document[0].rotation == 270
