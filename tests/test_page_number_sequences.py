"""Page numbers require edge, body-distance, sequence and label evidence."""

import pytest

from pdf2audiobook.config import Pdf
from pdf2audiobook.document.structure import pagination_cleanup
from pdf2audiobook.models import DocumentBlock

SIZES = [(600.0, 800.0)] * 4


def _block(page, ident, text, box):
    return DocumentBlock(
        id=ident,
        text=text,
        page_index=page,
        bbox=box,
        font_size=10,
        order=page * 10,
    )


def _sonnet_pages():
    blocks = []
    for page in range(4):
        blocks.extend(
            [
                _block(page, f"poem-{page}", str(page + 12), (290, 75, 310, 90)),
                _block(page, f"body-{page}", "Poem body line begins here.", (70, 130, 500, 150)),
                _block(page, f"folio-{page}", str(page + 40), (290, 765, 310, 780)),
            ]
        )
    return blocks


def test_poem_numerals_survive_while_edge_folios_are_removed():
    blocks = _sonnet_pages()
    warnings = []
    edits = pagination_cleanup(
        blocks, SIZES, Pdf(), page_labels=[str(n) for n in range(40, 44)], warnings=warnings
    )
    removed = {edit.block_id for edit in edits}
    assert removed == {f"folio-{page}" for page in range(4)}
    assert "Printed page numbers disagree with PDF page labels" not in warnings


def test_outermost_competing_edge_sequence_wins():
    blocks = []
    for page in range(4):
        blocks.extend(
            [
                _block(page, f"top-{page}", str(page + 1), (290, 18, 310, 32)),
                _block(page, f"body-{page}", "Text in the body of the page.", (70, 150, 500, 170)),
                _block(page, f"bottom-{page}", str(page + 40), (290, 765, 310, 780)),
            ]
        )
    warnings = []
    edits = pagination_cleanup(blocks, SIZES, Pdf(), warnings=warnings)
    assert {edit.block_id for edit in edits} == {f"top-{page}" for page in range(4)}
    assert warnings == []


@pytest.mark.parametrize("band", ["header", "footer", "footnote"])
def test_single_physical_folio_sequence_is_removed_even_near_body_text(band):
    blocks = []
    for page in range(4):
        blocks.append(_block(page, f"body-{page}", "Body text starts here.", (70, 100, 500, 120)))
        y = 35 if band == "header" else (750 if band == "footer" else 760)
        if band == "footnote":
            blocks.append(_block(page, f"note-{page}", "1. Source note.", (90, 740, 500, 752)))
            y = 760
        blocks.append(_block(page, f"folio-{page}", str(page + 1), (290, y, 310, y + 10)))
    edits = pagination_cleanup(blocks, SIZES, Pdf())
    assert {edit.block_id for edit in edits} == {f"folio-{page}" for page in range(4)}


def test_label_disagreement_warns_but_does_not_disable_folio_removal():
    blocks = [
        _block(page, f"body-{page}", "Page body text appears here.", (70, 130, 500, 150))
        for page in range(4)
    ] + [_block(page, f"folio-{page}", str(page + 40), (290, 765, 310, 780)) for page in range(4)]
    warnings = []
    edits = pagination_cleanup(
        blocks, SIZES, Pdf(), page_labels=["1", "2", "3", "4"], warnings=warnings
    )
    assert {edit.block_id for edit in edits} == {f"folio-{page}" for page in range(4)}
    assert warnings == ["Printed page numbers disagree with PDF page labels"]


def test_sequential_folios_within_twelve_points_of_full_width_body_are_removed():
    blocks = []
    for page in range(4):
        blocks.extend(
            [
                _block(page, f"body-{page}", "A body line near the footer.", (70, 680, 500, 700)),
                _block(page, f"folio-{page}", str(page + 1), (295, 710, 305, 720)),
            ]
        )

    edits = pagination_cleanup(blocks, SIZES, Pdf())

    assert {edit.block_id for edit in edits} == {f"folio-{page}" for page in range(4)}
