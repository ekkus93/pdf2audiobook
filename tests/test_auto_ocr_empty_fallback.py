"""Empty automatic OCR must not silently discard available embedded prose."""

from __future__ import annotations

import shutil
from pathlib import Path

import fitz
import pytest

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import extract_pdf


def _short_text_pdf(path: Path) -> None:
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=300)
        blank = page.get_pixmap()
        page.insert_image(page.rect, stream=blank.tobytes("png"))
        page.insert_text((45, 70), "Chapter 7", fontsize=16)
        doc.save(path)


@pytest.mark.parametrize("mode", ["auto", "always", "never"])
def test_empty_ocr_preserves_short_embedded_prose_only_in_auto_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    source = tmp_path / "short-heading.pdf"
    _short_text_pdf(source)
    calls = []

    def empty_ocr(*args, **kwargs):
        calls.append(True)
        return []

    monkeypatch.setattr("pdf2audiobook.pdf._cached_ocr_lines", empty_ocr)
    result = extract_pdf(source, Pdf(ocr=mode))
    assert bool(calls) is (mode != "never")
    if mode == "always":
        assert not result.spans
        assert any("OCR produced no text" in warning for warning in result.warnings)
    else:
        assert len(result.spans) == len(result.blocks) == 1
        assert result.spans[0].text == result.blocks[0].text == "Chapter 7"
        assert result.spans[0].origin == "embedded"
        assert result.spans[0].bbox is not None
    if mode == "auto":
        assert any("retained unverified embedded text" in warning for warning in result.warnings)
    else:
        assert not any(
            "retained unverified embedded text" in warning for warning in result.warnings
        )


def test_auto_ocr_empty_on_scanned_page_still_reports_no_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "blank.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=300)
        blank = page.get_pixmap()
        page.insert_image(page.rect, stream=blank.tobytes("png"))
        doc.save(source)
    monkeypatch.setattr("pdf2audiobook.pdf._cached_ocr_lines", lambda *a, **k: [])
    result = extract_pdf(source, Pdf(ocr="auto"))
    assert not result.spans
    assert any("OCR produced no text" in warning for warning in result.warnings)
    assert not any("retained unverified embedded text" in warning for warning in result.warnings)


def test_dense_vector_drawing_page_triggers_auto_ocr():
    from pdf2audiobook.pdf import _page_ocr_strategy

    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        for row in range(12):
            for column in range(10):
                x, y = 30 + column * 50, 30 + row * 60
                page.draw_rect(fitz.Rect(x, y, x + 24, y + 28), color=(0, 0, 0))
        usable, _issue, should_ocr, warnings = _page_ocr_strategy(page, [], Pdf(ocr="auto"), 1)
    assert not usable
    assert should_ocr
    assert warnings


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract is not installed")
def test_dense_vector_page_reaches_the_ocr_engine(monkeypatch, tmp_path):
    from pdf2audiobook import pdf

    source = tmp_path / "vector-outline.pdf"
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        for row in range(12):
            for column in range(10):
                x, y = 30 + column * 50, 30 + row * 60
                page.draw_rect(fitz.Rect(x, y, x + 24, y + 28), color=(0, 0, 0))
        document.save(source)
    original = pdf._cached_ocr_lines
    called = []

    def track_ocr(*args, **kwargs):
        called.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(pdf, "_cached_ocr_lines", track_ocr)
    result = pdf.extract_pdf(source, Pdf(ocr="auto"))
    assert called
    assert any("OCR" in warning for warning in result.warnings)
