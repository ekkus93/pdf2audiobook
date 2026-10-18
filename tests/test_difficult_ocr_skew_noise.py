"""Real-Tesseract acceptance for skewed, low-contrast, noisy synthetic scans."""
from __future__ import annotations

import shutil
from pathlib import Path

import fitz
import pytest

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import extract_pdf


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract unavailable")
@pytest.mark.parametrize("skew_degrees", [-1.5, 1.5])
def test_mild_skew_low_contrast_scan_is_preserved_without_embedded_duplication(
    tmp_path: Path, skew_degrees: float,
):
    source = tmp_path / "skewed-mixed.pdf"
    raster_source = fitz.open()
    page = raster_source.new_page(width=595, height=842)
    page.draw_rect(page.rect, color=None, fill=(0.89, 0.89, 0.89))
    page.insert_text((65, 96), "Chapter 8", fontsize=24, color=(0.24, 0.24, 0.24))
    page.insert_text(
        (65, 159), "Synthetic walnut travelers follow a narrow road.",
        fontsize=17, color=(0.24, 0.24, 0.24),
    )
    page.insert_text(
        (65, 217), "Gentle patterns test noisy scanned pages.",
        fontsize=17, color=(0.24, 0.24, 0.24),
    )
    for y in (270, 460, 680):
        page.draw_line((40, y), (510, y + 5), color=(0.78, 0.78, 0.78), width=0.6)
    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(2, 2).prerotate(skew_degrees), alpha=False,
    )
    raster_source.close()

    book = fitz.open()
    scanned = book.new_page(width=595, height=842)
    scanned.insert_image(scanned.rect, pixmap=pixmap)
    embedded = book.new_page(width=595, height=842)
    embedded.insert_text((65, 125), "Chapter 9", fontsize=24)
    embedded.insert_text((65, 190), "Embedded copper lanterns mark the path.", fontsize=17)
    book.save(source)
    book.close()

    settings = Pdf(ocr="auto", ocr_language="eng", ocr_dpi=300)
    cache = tmp_path / "ocr-cache"
    first = extract_pdf(source, settings, ocr_cache_dir=cache)
    second = extract_pdf(source, settings, ocr_cache_dir=cache)
    for document in (first, second):
        scanned_text = " ".join(
            span.text for span in document.spans if span.page_index == 0
        ).casefold()
        assert "synthetic walnut travelers" in scanned_text
        assert "gentle patterns test noisy" in scanned_text
        assert len([span for span in document.spans if span.origin == "ocr"]) >= 3
        assert all(
            span.origin == ("ocr" if span.page_index == 0 else "embedded")
            for span in document.spans
        )
        assert sum("copper lanterns" in span.text.lower() for span in document.spans) == 1
        assert all(span.bbox is not None for span in document.spans)
        assert [span.id for span in document.spans] == [
            block.id for block in document.blocks
        ]
    assert [(span.id, span.text, span.bbox) for span in first.spans] == [
        (span.id, span.text, span.bbox) for span in second.spans
    ]
    assert len(list(cache.glob("*.json"))) == 1
