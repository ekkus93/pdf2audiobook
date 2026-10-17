"""Offline numbered-list and pagination PDF fixture acceptance."""

import fitz

from pdf2audiobook.config import Pdf
from pdf2audiobook.document.structure import pagination_cleanup
from pdf2audiobook.pdf import extract_pdf


def test_repeated_headers_and_sequential_folios_do_not_remove_numbered_body(tmp_path):
    source = tmp_path / "numbered-list.pdf"
    doc = fitz.open()
    for page_number in range(1, 4):
        page = doc.new_page(width=600, height=800)
        page.insert_text((250, 35), "Field Guide", fontsize=9)
        page.insert_text(
            (65, 200),
            f"Page {page_number} explains the procedure with original body prose.",
            fontsize=11,
        )
        page.insert_text((65, 300), "1. Preserve the numbered first step.", fontsize=11)
        page.insert_text((65, 322), "2. Preserve the numbered second step.", fontsize=11)
        page.insert_text((295, 780), str(page_number), fontsize=9)
    doc.save(source)
    doc.close()

    extracted = extract_pdf(source, Pdf(ocr="never"))
    edits = pagination_cleanup(extracted.blocks, extracted.page_sizes, Pdf())
    removed = {edit.block_id for edit in edits}
    assert len(edits) == 6
    assert all(edit.accepted and edit.replacement == "" for edit in edits)
    assert {edit.original for edit in edits} == {"Field Guide", "1", "2", "3"}
    assert sum("Preserve the numbered first step" in block.text
               for block in extracted.blocks if block.id not in removed) == 3
    assert sum("Preserve the numbered second step" in block.text
               for block in extracted.blocks if block.id not in removed) == 3
    assert all(block.id in {span.id for span in extracted.spans}
               for block in extracted.blocks)
