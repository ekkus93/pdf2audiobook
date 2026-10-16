"""Real PDF fixture: repeated running titles must not erase prose."""
from pathlib import Path

import fitz

from pdf2audiobook.config import Pdf
from pdf2audiobook.document.structure import pagination_cleanup
from pdf2audiobook.pdf import extract_pdf


def test_running_title_and_prose(tmp_path: Path):
    source = tmp_path / "book.pdf"
    doc = fitz.open()
    for index in range(3):
        page = doc.new_page(width=600, height=840)
        page.insert_text((200, 30), "Sample Book", fontsize=10)
        page.insert_text((72, 160), f"Original passage {index} must remain.", fontsize=12)
    doc.save(source)
    doc.close()
    extracted = extract_pdf(source, Pdf(ocr="never"))
    edits = pagination_cleanup(extracted.blocks, extracted.page_sizes, Pdf())
    removed = {edit.block_id for edit in edits if edit.accepted}
    assert sum(block.id in removed for block in extracted.blocks
               if block.text == "Sample Book") == 3
    assert all(block.id not in removed for block in extracted.blocks
               if "Original passage" in block.text)
