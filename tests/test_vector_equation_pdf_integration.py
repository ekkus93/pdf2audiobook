"""Offline PDF integration: non-prose geometry is advisory, never invented."""

import fitz

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import extract_pdf


def test_vector_figure_and_equation_preserve_source_text(tmp_path):
    source = tmp_path / "illustrated.pdf"
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        page.insert_text((72, 80), "Chapter One", fontsize=15)
        page.insert_text(
            (72, 110), "This is a normal paragraph that must remain intact.",
            fontsize=12,
        )
        # Two overlapping vector paths: no raster images and no text inferred
        # from the diagram. The nearby explicit caption is still source text.
        page.draw_circle((110, 200), 35, color=(0, 0, 0))
        page.draw_circle((140, 210), 35, color=(0, 0, 0))
        page.insert_text((80, 265), "Figure 1: A two-circle diagram", fontsize=12)
        page.insert_text((80, 320), "E = mc2", fontsize=12)
        document.save(source)

    extracted = extract_pdf(source, Pdf(ocr="never"))
    source_texts = [span.text for span in extracted.spans]
    block_texts = [block.text for block in extracted.blocks]
    assert block_texts == source_texts
    assert block_texts == [
        "Chapter One",
        "This is a normal paragraph that must remain intact.",
        "Figure 1: A two-circle diagram",
        "E = mc2",
    ]
    kinds = {block.text: block.kind for block in extracted.blocks}
    assert kinds["Figure 1: A two-circle diagram"] == "caption"
    assert kinds["E = mc2"] == "equation"
    assert any("vector artwork" in warning for warning in extracted.warnings)
    assert any("geometry-backed caption" in warning for warning in extracted.warnings)
    assert any("likely displayed equation" in warning for warning in extracted.warnings)
    assert all(span.origin == "embedded" for span in extracted.spans)
