"""Vector-only figures are reviewable even without embedded raster images."""

import fitz

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import extract_pdf
from pdf2audiobook.special_material import vector_artwork_warnings


def test_two_large_vector_shapes_trigger_review_without_text_loss(tmp_path):
    source = tmp_path / "vector.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (55, 85),
        "The two boxes below illustrate a multi-step process in this book.",
    )
    page.draw_rect(fitz.Rect(100, 150, 250, 240), color=(0, 0, 0))
    page.draw_rect(fitz.Rect(320, 150, 470, 240), color=(0, 0, 0))
    doc.save(source)
    doc.close()

    extracted = extract_pdf(source, Pdf(ocr="never"))
    assert any("substantial vector artwork" in item for item in extracted.warnings)
    assert any("two boxes below" in span.text for span in extracted.spans)
    assert all(span.origin == "embedded" for span in extracted.spans)


def test_single_border_and_underline_do_not_trigger_vector_warning():
    class Page:
        class Crop:
            width = 600
            height = 800

        cropbox = Crop()

        def get_drawings(self):
            return [
                {"rect": (20, 20, 580, 780)},
                {"rect": (50, 100, 400, 101)},
            ]

    assert vector_artwork_warnings(Page(), page_number=1) == []


def test_vector_detector_failure_warns_without_crashing():
    class Broken:
        class Crop:
            width = 600
            height = 800

        cropbox = Crop()

        def get_drawings(self):
            raise RuntimeError("malformed vector content")

    assert "inspection unavailable" in vector_artwork_warnings(
        Broken(), page_number=2,
    )[0]
