"""Competing page-number sequences that are equally near the paper edge are both kept (R47)."""

from pdf2audiobook.config import Pdf
from pdf2audiobook.document.structure import pagination_cleanup
from pdf2audiobook.models import DocumentBlock

SIZES = [(600.0, 800.0)] * 4


def _block(page, ident, text, box):
    return DocumentBlock(
        id=ident, text=text, page_index=page, bbox=box, font_size=10, order=page * 10
    )


def _competing(top_y, bottom_y):
    blocks = []
    for page in range(4):
        blocks.extend(
            [
                _block(page, f"top-{page}", str(page + 1), (290, top_y, 310, top_y + 14)),
                _block(page, f"body-{page}", "Text in the body of the page.", (70, 150, 500, 170)),
                _block(page, f"bottom-{page}", str(page + 40), (290, bottom_y, 310, bottom_y + 14)),
            ]
        )
    return blocks


def test_equally_near_sequences_are_both_kept_with_one_warning():
    warnings = []
    # 18pt from the top edge and 18pt from the bottom edge.
    edits = pagination_cleanup(_competing(18, 768), SIZES, Pdf(), warnings=warnings)
    assert edits == []
    assert warnings == ["Multiple page-number sequences retained; verify pagination"]


def test_a_clearly_nearer_sequence_wins_without_a_warning():
    warnings = []
    edits = pagination_cleanup(_competing(10, 768), SIZES, Pdf(), warnings=warnings)
    assert {edit.block_id for edit in edits} == {f"top-{page}" for page in range(4)}
    assert warnings == []
