"""Vector-only PDF figure captions are conservatively source-classified."""

from pathlib import Path

import fitz

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import extract_pdf


def _pdf_with_shapes(path: Path, rectangles: list[fitz.Rect], caption_y: int) -> None:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((55, 100), "The source prose must be preserved.", fontsize=12)
    page.insert_text((55, 130), "Another full line of ordinary prose.", fontsize=12)
    for rect in rectangles:
        page.draw_rect(rect, color=(0, 0, 0), width=1)
    page.insert_text((100, caption_y), "Figure 1: A vector-only diagram", fontsize=11)
    document.save(path)
    document.close()


def test_clustered_vector_diagram_caption_is_typed_without_text_loss(tmp_path: Path):
    path = tmp_path / "vector.pdf"
    _pdf_with_shapes(
        path,
        [fitz.Rect(100, 250, 220, 290), fitz.Rect(100, 300, 220, 340)],
        365,
    )
    extracted = extract_pdf(path, Pdf(ocr="never"))
    assert any(
        block.kind == "caption" and block.text == "Figure 1: A vector-only diagram"
        for block in extracted.blocks
    )
    assert any("vector artwork detected" in warning for warning in extracted.warnings)
    assert any("geometry-backed caption" in warning for warning in extracted.warnings)
    assert any("source prose must be preserved" in span.text for span in extracted.spans)


def test_single_rectangle_is_not_sufficient_for_vector_caption(tmp_path: Path):
    path = tmp_path / "one-rectangle.pdf"
    _pdf_with_shapes(path, [fitz.Rect(100, 250, 220, 340)], 365)
    extracted = extract_pdf(path, Pdf(ocr="never"))
    assert not any(block.kind == "caption" for block in extracted.blocks)
    assert any("Figure 1: A vector-only diagram" in span.text for span in extracted.spans)


def test_distant_vector_art_is_not_assumed_to_be_a_caption(tmp_path: Path):
    path = tmp_path / "distant.pdf"
    _pdf_with_shapes(
        path,
        [fitz.Rect(100, 250, 220, 290), fitz.Rect(100, 300, 220, 340)],
        740,
    )
    extracted = extract_pdf(path, Pdf(ocr="never"))
    assert not any(block.kind == "caption" for block in extracted.blocks)
    assert any("Figure 1: A vector-only diagram" in span.text for span in extracted.spans)
