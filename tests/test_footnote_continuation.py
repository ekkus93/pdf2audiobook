"""Conservative classification of wrapped footnotes retains original provenance."""

from pathlib import Path

import fitz

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import _footnote_line_indices, extract_pdf


def _line(text: str, y: float, *, size: float = 12, x: float = 55) -> dict:
    return {"text": text, "bbox": (x, y, x + 250, y + size), "size": size}


def test_confirmed_note_gathers_only_adjacent_continuation_lines():
    lines = [
        _line("A body paragraph", 100),
        _line("Another body paragraph", 140),
        _line("1. A numbered footnote", 640, size=8),
        _line("continued on the following line", 651, size=8, x=66),
        _line("and the next line", 662, size=8, x=66),
        _line("Body prose must not be consumed.", 676),
    ]
    assert _footnote_line_indices(lines, page_height=842, table_regions=[]) == {2, 3, 4}


def test_other_columns_large_gaps_and_unanchored_small_text_are_not_notes():
    body = [_line("First body paragraph", 100), _line("Second body paragraph", 140)]
    assert (
        _footnote_line_indices(
            body + [_line("Unnumbered small print", 640, size=8)],
            page_height=842,
            table_regions=[],
        )
        == set()
    )
    lines = body + [
        _line("1. Confirmed footnote", 640, size=8),
        _line("Remote annotation", 675, size=8),
        _line("Side column", 684, size=8, x=360),
    ]
    assert _footnote_line_indices(lines, page_height=842, table_regions=[]) == {2}
    lines[3] = _line("Adjacent table cell", 651, size=8)
    assert _footnote_line_indices(
        lines,
        page_height=842,
        table_regions=[(45, 648, 400, 665)],
    ) == {2}


def test_extraction_keeps_wrapped_footnote_spans_unchanged(tmp_path: Path):
    source = tmp_path / "wrapped-footnotes.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    for y, value, size in [
        (100, "Chapter 1", 16),
        (140, "First body paragraph", 12),
        (180, "Second body paragraph", 12),
        (665, "1. This numbered footnote begins here", 8),
        (677, "and continues into the next printed line", 8),
        (689, "without another note marker", 8),
    ]:
        page.insert_text((55, y), value, fontsize=size)
    doc.save(source)
    doc.close()

    extracted = extract_pdf(source, Pdf(ocr="never"))
    footnotes = [block for block in extracted.blocks if block.kind == "footnote"]
    assert [block.text for block in footnotes] == [
        "1. This numbered footnote begins here",
        "and continues into the next printed line",
        "without another note marker",
    ]
    assert len(extracted.spans) == len(extracted.blocks) == 6
    assert all(
        len(block.span_ids) == 1
        and any(span.id == block.id and span.text == block.text for span in extracted.spans)
        for block in footnotes
    )
    assert any("footnote anchor(s)/continuation" in warning for warning in extracted.warnings)
