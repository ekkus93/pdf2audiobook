"""End-to-end PDF extraction + conservative pagination classification fixtures."""
from __future__ import annotations

from pathlib import Path

import fitz

from pdf2audiobook.config import Pdf
from pdf2audiobook.document.structure import pagination_cleanup
from pdf2audiobook.pdf import extract_pdf


def make_folio_pdf(path: Path, folios: list[str], *, mirrored: bool = False) -> None:
    doc = fitz.open()
    for index, label in enumerate(folios):
        page = doc.new_page(width=600, height=840)
        page.insert_text(
            (72, 160), f"Ordinary prose from page {index + 1} must be retained.",
            fontsize=12,
        )
        x = (18 if index % 2 == 0 else 570) if mirrored else 290
        page.insert_text((x, 817), label, fontsize=10)
    doc.save(path)
    doc.close()


def check_folios(source: Path, expected: list[str]) -> None:
    extracted = extract_pdf(source, Pdf(ocr="never"))
    edits = pagination_cleanup(extracted.blocks, extracted.page_sizes, Pdf())
    removed = {edit.block_id for edit in edits if edit.accepted}
    removed_blocks = [block for block in extracted.blocks if block.id in removed]
    assert [block.text for block in removed_blocks] == expected
    assert all(edit.original in expected and edit.replacement == "" for edit in edits)
    assert all(
        block.id not in removed
        for block in extracted.blocks if "Ordinary prose" in block.text
    )
    assert len([block for block in extracted.blocks
                if "Ordinary prose" in block.text]) == len(expected)


def test_pdf_roman_frontmatter_folios_are_audited(tmp_path: Path):
    source = tmp_path / "roman.pdf"
    make_folio_pdf(source, ["i", "ii", "iii", "iv"])
    check_folios(source, ["i", "ii", "iii", "iv"])


def test_pdf_mirrored_arabic_folios_are_audited(tmp_path: Path):
    source = tmp_path / "mirrored.pdf"
    make_folio_pdf(source, ["10", "11", "12", "13"], mirrored=True)
    check_folios(source, ["10", "11", "12", "13"])
