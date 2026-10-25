"""Text drawn as vector outlines is OCRed even when its drawings cover little area (R69)."""

import shutil
from pathlib import Path

import pymupdf
import pytest

from pdf2audiobook import pdf
from pdf2audiobook.config import Pdf

# Four lines of prose converted to outlines with Ghostscript -dNoOutputFonts:
# no text layer, no images, 220 glyph paths covering about 2% of the page.
FIXTURE = Path(__file__).parent / "fixtures" / "outlined_text.pdf"


def _fixture_page_facts():
    with pymupdf.open(FIXTURE) as document:
        page = document[0]
        area = float(page.cropbox.width) * float(page.cropbox.height)
        covered = sum(item["rect"].width * item["rect"].height for item in page.get_drawings())
        return page.get_text().strip(), len(page.get_images()), covered / area


def test_fixture_is_outlined_text_below_the_old_coverage_threshold():
    text, images, coverage = _fixture_page_facts()
    assert text == "" and images == 0
    assert coverage < 0.15


def test_outlined_text_page_selects_ocr_in_auto_mode():
    with pymupdf.open(FIXTURE) as document:
        usable, _issue, should_ocr, warnings = pdf._page_ocr_strategy(
            document[0], [], Pdf(ocr="auto"), 1
        )
    assert not usable
    assert should_ocr
    assert any("attempting OCR" in warning for warning in warnings)


def test_a_single_rule_is_not_sent_to_ocr(tmp_path):
    source = tmp_path / "rule.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=600, height=800)
        page.draw_line((50, 400), (550, 400))
        document.save(source)
    result = pdf.extract_pdf(source, Pdf(ocr="auto"))
    assert any("no readable text (no text or drawings found)" in w for w in result.warnings)
    assert not any("OCR not needed" in warning for warning in result.warnings)
    assert not any("drawings without readable text" in warning for warning in result.warnings)


def test_drawing_only_page_without_ocr_never_claims_ocr_is_not_needed():
    result = pdf.extract_pdf(FIXTURE, Pdf(ocr="never"))
    assert any("no readable text (OCR disabled)" in warning for warning in result.warnings)
    assert not any("OCR not needed" in warning for warning in result.warnings)


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract is not installed")
def test_outlined_text_page_is_recognized_by_ocr():
    result = pdf.extract_pdf(FIXTURE, Pdf(ocr="auto"))
    text = " ".join(block.text for block in result.blocks).casefold()
    assert "harbour" in text and "ferry" in text
    assert not any("OCR not needed" in warning for warning in result.warnings)
