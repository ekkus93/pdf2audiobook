"""Scanned-book text layers: line fragments, tight folios and prose "Chapter" lines.

Regressions from a real public-domain scan (Internet Archive cu31924026355879),
reproduced here with synthetic text only.
"""

import pymupdf

from pdf2audiobook.config import Pdf
from pdf2audiobook.document.structure import chapter_coverage_report, pagination_cleanup
from pdf2audiobook.models import BookManifest, Chapter
from pdf2audiobook.pdf import _heading_line, extract_pdf
from pdf2audiobook.reading_order import merge_line_fragments


def line(text, x0, y0, x1, y1, size=9.0):
    return {"text": text, "bbox": (x0, y0, x1, y1), "font": "GlyphLessFont", "size": size}


def test_word_group_fragments_on_one_baseline_are_joined_with_parts():
    merged = merge_line_fragments(
        [
            line("measures by", 27, 429, 83, 440),
            line("four-eight", 89, 431, 131, 439, size=7.0),
            line("time.", 138, 430, 159, 439),
            line("Next printed line.", 27, 442, 120, 451),
        ]
    )
    assert [item["text"] for item in merged] == [
        "measures by four-eight time.",
        "Next printed line.",
    ]
    assert [part["text"] for part in merged[0]["parts"]] == ["measures by", "four-eight", "time."]
    assert merged[0]["bbox"] == (27, 429, 159, 440)
    assert "parts" not in merged[1]


def test_wide_gaps_and_column_gutters_are_never_bridged():
    lines = []
    # Five justified left-column lines end at x=280; right column starts at 292.
    for row in range(5):
        y = 100 + 12 * row
        lines += [line(f"left {row}", 60, y, 280, y + 9), line(f"right {row}", 292, y, 510, y + 9)]
    lines.append(line("label", 30, 200, 60, 209))
    lines.append(line("far value", 120, 200, 200, 209))  # gap 60 > 1.5 line heights
    merged = merge_line_fragments(lines)
    assert merged == lines


def test_malformed_records_pass_through_unmerged():
    odd = [line("one", 10, 10, 30, 19), {"text": "two", "bbox": None}, "bad"]
    assert merge_line_fragments(odd) == odd


def test_fragmented_pdf_lines_become_one_block_with_every_span(tmp_path):
    source = tmp_path / "fragments.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=500)
    x = 30.0
    for word in ("Fragmented", "printed", "line", "here."):
        # A ~1 em justified word space makes PyMuPDF report separate lines,
        # as it does for scanned-book text layers.
        page.insert_text((x, 100), word, fontsize=9)
        x += pymupdf.get_text_length(word, fontsize=9) + 10
    page.insert_text((30, 140), "A second ordinary line of text.", fontsize=9)
    doc.save(source)
    doc.close()
    extracted = extract_pdf(source, Pdf(ocr="never"))
    assert [block.text for block in extracted.blocks] == [
        "Fragmented printed line here.",
        "A second ordinary line of text.",
    ]
    first = extracted.blocks[0]
    assert len(first.span_ids) == 4
    spans = {span.id: span.text for span in extracted.spans}
    assert [spans[span_id] for span_id in first.span_ids] == [
        "Fragmented",
        "printed",
        "line",
        "here.",
    ]
    manifest = BookManifest(
        input_sha256="0" * 64,
        title="t",
        source_path="fragments.pdf",
        spans=extracted.spans,
        blocks=extracted.blocks,
        chapters=[Chapter(id="c", number=1, title="t", start_block=0, end_block=2, confidence=1)],
    )
    assert chapter_coverage_report(manifest)["source_spans"] == 5


def _scan_pdf(path, pages, *, offsets=None, citation_page=None):
    """Small scanned-book pages: full-width body ending just above a centered folio."""
    doc = pymupdf.open()
    contents = doc.new_page(width=303, height=510)
    contents.insert_text((40, 60), "CONTENTS", fontsize=12)
    for row, number in enumerate(range(1, pages + 1)):
        contents.insert_text((40, 90 + 14 * row), f"Section {row + 1}", fontsize=9)
        contents.insert_text((266, 90 + 14 * row), str(number), fontsize=9)
    for index in range(pages):
        shift = (offsets or {}).get(index, 0)
        page = doc.new_page(width=303, height=510)
        for row in range(30):
            page.insert_text(
                (28 + shift, 80 + 12.6 * row),
                f"Body prose line {row} on page {index} runs right across the full",
                fontsize=8,
            )
        if index == citation_page:
            page.insert_text((156 + shift, 461), "(Source 1-4)", fontsize=7)
        page.insert_text((149 + shift, 474), str(index + 1), fontsize=8)
    doc.save(path)
    doc.close()


def _removed(path):
    extracted = extract_pdf(path, Pdf(ocr="never"))
    edits = pagination_cleanup(extracted.blocks, extracted.page_sizes, Pdf())
    by_id = {block.id: block for block in extracted.blocks}
    return [(by_id[edit.block_id].page_index, edit.original) for edit in edits if edit.accepted]


def test_tight_centered_folios_are_removed_even_when_listed_in_contents(tmp_path):
    source = tmp_path / "scan.pdf"
    _scan_pdf(source, 5)
    # Folios 1..5 sit ~4pt under full-width body text and also appear as page
    # references on the contents page, which itself must stay intact.
    assert _removed(source) == [(page, str(page)) for page in range(1, 6)]


def test_folios_on_sideways_drifting_scans_and_under_citations(tmp_path):
    source = tmp_path / "drift.pdf"
    _scan_pdf(source, 5, offsets={2: 21}, citation_page=3)
    assert _removed(source) == [(page, str(page)) for page in range(1, 6)]


def test_prose_starting_with_a_chapter_reference_is_not_a_heading():
    assert _heading_line("CHAPTER IV RHYME")
    assert _heading_line("Chapter 3: The Return")
    assert _heading_line("PREFACE")
    assert not _heading_line("Chapter IV regarding the change in Shakespeare's blank")
    assert not _heading_line(
        "Introduction of the new rules took many years and was opposed by nearly everyone"
    )
