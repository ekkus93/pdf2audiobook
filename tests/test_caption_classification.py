"""Figure/table caption typing preserves source and avoids prose false positives."""

import fitz

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import extract_pdf
from pdf2audiobook.special_material import caption_line_indices


class FakePage:
    def __init__(self, boxes):
        self.boxes = boxes

    def get_image_info(self):
        return [{"bbox": box} for box in self.boxes]


def test_caption_requires_explicit_label_and_adjacent_matching_region():
    lines = [
        {"text": "Figure 1: A square.", "bbox": (100, 224, 280, 237)},
        {"text": "Figure 1 shows the next step.", "bbox": (100, 250, 320, 264)},
        {"text": "Figure 2: A distant square.", "bbox": (100, 440, 300, 454)},
        {"text": "Table 2: Experimental results", "bbox": (100, 500, 330, 515)},
        {"text": "Table 3: No matching table", "bbox": (100, 610, 330, 625)},
    ]
    result, warnings = caption_line_indices(
        FakePage([(100, 100, 310, 215)]),
        lines,
        [(100, 522, 350, 610)],
        page_number=1,
    )
    assert result == {0, 3}
    assert "original text preserved" in warnings[0]


def test_image_scans_do_not_mark_embedded_ocr_text_as_caption():
    result, _ = caption_line_indices(
        FakePage([(0, 0, 600, 800)]),
        [{"text": "Figure 1: The page.", "bbox": (100, 300, 280, 315)}],
        [],
        page_number=1,
    )
    assert not result


def test_synthetic_pdf_caption_is_source_linked_and_non_destructive(tmp_path):
    source = tmp_path / "figure.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (70, 80),
        "This paragraph has enough normal selectable text to skip OCR.",
    )
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 16, 16), False)
    page.insert_image(fitz.Rect(100, 130, 310, 230), pixmap=pix)
    page.insert_text((100, 250), "Figure 1: A simple rectangular diagram.")
    page.insert_text((70, 400), "Figure 1 shows the result in ordinary prose.")
    doc.save(source)
    doc.close()
    extracted = extract_pdf(source, Pdf(ocr="never"))
    captions = [block for block in extracted.blocks if block.kind == "caption"]
    assert len(captions) == 1
    assert captions[0].text == "Figure 1: A simple rectangular diagram."
    assert captions[0].span_ids == [captions[0].id]
    assert any(span.id == captions[0].id and span.text == captions[0].text
               for span in extracted.spans)
    assert any("geometry-backed caption" in warning for warning in extracted.warnings)
    assert any("Figure 1 shows" in block.text and block.kind != "caption"
               for block in extracted.blocks)
