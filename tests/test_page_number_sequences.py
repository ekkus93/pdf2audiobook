"""Page numbers require edge, body-distance, sequence and label evidence."""

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
    edits = pagination_cleanup(blocks, SIZES, Pdf(), page_labels=[str(n) for n in range(40, 44)])
    removed = {edit.block_id for edit in edits}
    assert removed == {f"folio-{page}" for page in range(4)}


def test_competing_edge_sequences_are_kept_with_a_review_warning():
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
    assert pagination_cleanup(blocks, SIZES, Pdf(), warnings=warnings) == []
    assert warnings == ["Multiple page-number sequences retained; verify pagination"]


def test_explicit_page_labels_must_agree_with_folio_sequence():
    blocks = [
        _block(page, f"body-{page}", "Page body text appears here.", (70, 130, 500, 150))
        for page in range(4)
    ] + [_block(page, f"folio-{page}", str(page + 40), (290, 765, 310, 780)) for page in range(4)]
    assert pagination_cleanup(blocks, SIZES, Pdf(), page_labels=["1", "2", "3", "4"]) == []
