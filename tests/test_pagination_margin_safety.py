"""Fail-closed pagination classification of legitimate margin prose and lists."""

from pdf2audiobook.config import Pdf
from pdf2audiobook.document.structure import pagination_cleanup
from pdf2audiobook.models import DocumentBlock


def _block(page: int, name: str, text: str, x: float, y: float, kind="unknown"):
    return DocumentBlock(
        id=f"p{page}-{name}",
        page_index=page,
        text=text,
        kind=kind,
        bbox=(x, y, x + max(10, min(190, len(text) * 7)), y + 12),
        font_size=11,
    )


def test_verified_folios_and_headers_removed_but_margin_prose_preserved():
    blocks = []
    for page in range(3):
        blocks.extend(
            [
                _block(page, "header", "Running Title", 200, 20),
                _block(page, "body", f"Chapter body paragraph {page}", 65, 180),
                _block(page, "folio", str(page + 1), 295, 760),
            ]
        )
    blocks.extend(
        [
            _block(1, "quote", "“This is a quotation.”", 45, 50),
            _block(2, "list", "1. A substantive list entry", 45, 50),
            _block(2, "footnote", "2. An actual footnote", 45, 740, kind="footnote"),
        ]
    )
    edits = pagination_cleanup(blocks, [(600, 800)] * 3, Pdf())
    removed = {edit.block_id for edit in edits}
    assert removed == {
        *(f"p{page}-header" for page in range(3)),
        *(f"p{page}-folio" for page in range(3)),
    }
    assert all(edit.accepted and edit.replacement == "" for edit in edits)
    assert {edit.original for edit in edits} == {
        "Running Title", "1", "2", "3"
    }


def test_interior_repeated_text_and_unaligned_numbers_are_not_deleted():
    blocks = [
        _block(page, "header", "A short repeated phrase", 65, 25)
        for page in range(3)
    ]
    blocks.append(_block(0, "body", "A short repeated phrase", 65, 180))
    blocks.extend(
        _block(page, "number", str(page + 1), 88, 760)
        for page in range(3)
    )
    assert pagination_cleanup(blocks, [(600, 800)] * 3, Pdf()) == []


def test_multiple_margin_numbers_are_ambiguous_not_folios():
    blocks = []
    for page in range(3):
        blocks.extend(
            [
                _block(page, "folio", str(page + 1), 290, 755),
                _block(page, "reference", str(page + 11), 420, 760),
                _block(page, "body", "Ordinary prose", 70, 160),
            ]
        )
    assert pagination_cleanup(blocks, [(600, 800)] * 3, Pdf()) == []


def test_three_page_roman_folio_sequence_requires_corroboration():
    blocks = [
        _block(page, "roman", numeral, 295, 755)
        for page, numeral in enumerate(("i", "ii", "iii"))
    ]
    edits = pagination_cleanup(blocks, [(600, 800)] * 3, Pdf())
    assert {edit.block_id for edit in edits} == {
        "p0-roman", "p1-roman", "p2-roman"
    }
    # A two-page Roman sequence alone is not enough evidence for deletion.
    assert pagination_cleanup(blocks[:2], [(600, 800)] * 2, Pdf()) == []
