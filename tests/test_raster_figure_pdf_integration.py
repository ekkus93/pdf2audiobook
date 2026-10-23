"""Offline embedded-image review does not alter source transcript."""

import fitz

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import extract_pdf


def test_raster_figure_warning_preserves_embedded_paragraph(tmp_path):
    source = tmp_path / "raster-figure.pdf"
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 32, 32), False)
    pixmap.clear_with(200)
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        page.insert_text(
            (72, 80),
            "This source paragraph is present and must remain intact.",
            fontsize=12,
        )
        page.insert_image(
            fitz.Rect(100, 150, 350, 400),
            stream=pixmap.tobytes("png"),
        )
        document.save(source)

    extracted = extract_pdf(source, Pdf(ocr="never"))
    assert [block.text for block in extracted.blocks] == [
        "This source paragraph is present and must remain intact."
    ]
    assert [span.text for span in extracted.spans] == [
        "This source paragraph is present and must remain intact."
    ]
    assert extracted.spans[0].origin == "embedded"
    assert any("embedded image detected" in item for item in extracted.warnings)
    assert any("review manually" in item for item in extracted.warnings)
