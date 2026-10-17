"""Conservative pagination: numbered body lists must not become folios."""

from pdf2audiobook.config import Pdf
from pdf2audiobook.document.structure import pagination_cleanup
from pdf2audiobook.models import DocumentBlock


def _block(page: int, number: int, text: str, y: float, x: float = 280) -> DocumentBlock:
    return DocumentBlock(
        id=f"p{page}-n{number}",
        page_index=page,
        text=text,
        bbox=(x, y, x + 20, y + 10),
        font_size=10,
        order=page * 100 + number,
    )


def test_multiple_margin_numerals_per_page_are_not_assumed_to_be_page_numbers():
    blocks = [
        _block(0, 0, "This is substantive chapter text.", 200, 50),
        _block(0, 1, "1", 755),
        _block(0, 2, "2", 782),
        _block(1, 0, "The next page contains more prose.", 200, 50),
        _block(1, 1, "2", 755),
        _block(1, 2, "3", 782),
        _block(2, 0, "Further chapter prose follows.", 200, 50),
        _block(2, 1, "3", 755),
        _block(2, 2, "4", 782),
    ]
    edits = pagination_cleanup(blocks, [(595, 842)] * 3, Pdf())
    assert edits == []


def test_unambiguous_sequential_folios_remain_removable():
    blocks = [
        _block(0, 0, "First page prose retained.", 200, 50),
        _block(0, 1, "1", 780),
        _block(1, 0, "Second page prose retained.", 200, 50),
        _block(1, 1, "2", 780),
        _block(2, 0, "Third page prose retained.", 200, 50),
        _block(2, 1, "3", 780),
    ]
    edits = pagination_cleanup(blocks, [(595, 842)] * 3, Pdf())
    assert {edit.block_id for edit in edits} == {
        "p0-n1", "p1-n1", "p2-n1"
    }
    assert all(edit.accepted and edit.replacement == "" for edit in edits)


def test_ambiguous_page_does_not_corroborate_adjacent_folio():
    blocks = [
        _block(0, 0, "First page prose retained.", 200, 50),
        _block(0, 1, "1", 780),
        _block(1, 0, "Second page prose retained.", 200, 50),
        _block(1, 1, "2", 755),
        _block(1, 2, "3", 780),
    ]
    assert pagination_cleanup(blocks, [(595, 842)] * 2, Pdf()) == []
