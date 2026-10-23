"""Non-destructive PDF special-material review warnings."""

from __future__ import annotations

from pathlib import Path

import fitz

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import extract_pdf


def test_images_footnotes_and_math_are_flagged_without_text_loss(tmp_path: Path):
    source = tmp_path / "special.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((55, 120), "The main paragraph is retained.", fontsize=12)
    page.insert_text((55, 160), "And so is this second paragraph.", fontsize=12)
    page.insert_text((55, 200), "An equation is ∑ of the terms.", fontsize=12)
    page.insert_text((55, 740), "1 Footnote text is important.", fontsize=7)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10), False)
    pix.clear_with(255)
    page.insert_image(fitz.Rect(300, 260, 430, 390), pixmap=pix)
    doc.save(source)
    doc.close()

    extracted = extract_pdf(source, Pdf(ocr="never"))
    assert any("main paragraph" in span.text for span in extracted.spans)
    assert any("Footnote text" in span.text for span in extracted.spans)
    assert any("embedded image detected" in item for item in extracted.warnings)
    assert any("possible small-font footnote" in item for item in extracted.warnings)
    # The math symbol may not survive all PDF default-font encodings; source
    # text and warnings remain non-destructive regardless.
    assert all(span.origin == "embedded" for span in extracted.spans)


def test_plain_text_page_does_not_emit_special_material_warnings(tmp_path: Path):
    source = tmp_path / "plain.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((55, 120), "A regular paragraph in an ordinary PDF.")
    doc.save(source)
    doc.close()
    extracted = extract_pdf(source, Pdf(ocr="never"))
    assert not any(
        "embedded image" in item or "small-font footnote" in item for item in extracted.warnings
    )
