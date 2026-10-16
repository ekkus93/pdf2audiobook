"""Pagination safety: repeated margin prose must not disappear."""
from __future__ import annotations

from pathlib import Path

import fitz

from pdf2audiobook.config import Pdf
from pdf2audiobook.document.structure import pagination_cleanup
from pdf2audiobook.pdf import extract_pdf


def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    for page_num in range(8):
        page = doc.new_page(width=595, height=842)
        if page_num < 2:
            # A repeated first line of dialogue in the header band, followed
            # immediately by the rest of the paragraph.
            page.insert_text((55, 60), "We meet again", fontsize=11)
            page.insert_text(
                (55, 80), f"and continue the conversation on page {page_num}.",
                fontsize=11,
            )
        elif page_num < 4:
            # A genuine running title has ample separation from body text.
            page.insert_text((290, 35), "Running Title", fontsize=10)
            page.insert_text(
                (55, 160), f"Distinct body prose for page {page_num}.",
                fontsize=11,
            )
        elif page_num < 6:
            # Short repeated unquoted speech must remain intact.
            page.insert_text((55, 60), "No", fontsize=11)
            page.insert_text((55, 80), "was the only answer.", fontsize=11)
        else:
            # Consecutive numeric list labels at the top margin are not folios
            # when a nearby line continues the list item.
            page.insert_text((30, 60), str(page_num + 1), fontsize=10)
            page.insert_text(
                (30, 80), f"List item content for page {page_num}.",
                fontsize=11,
            )
    doc.save(path)
    doc.close()


def test_margin_body_continuity_prevents_false_pagination(tmp_path: Path):
    source = tmp_path / "margin-prose.pdf"
    _make_pdf(source)
    extracted = extract_pdf(source, Pdf(ocr="never"))
    edits = pagination_cleanup(extracted.blocks, extracted.page_sizes, Pdf())
    deleted = {(block.page_index, block.text) for block in extracted.blocks
               if block.id in {edit.block_id for edit in edits}}
    assert (2, "Running Title") in deleted
    assert (3, "Running Title") in deleted
    assert not any(page in {0, 1, 4, 5, 6, 7} for page, _ in deleted)
    assert len(deleted) == 2
