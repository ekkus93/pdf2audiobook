"""Substantive margin prose must survive pagination cleanup."""

import pytest

from pdf2audiobook.config import Pdf
from pdf2audiobook.document.structure import pagination_cleanup
from pdf2audiobook.models import DocumentBlock

PAGE = (600.0, 800.0)


def block(page, text, *, ident, top=True, kind="paragraph", font_size=10):
    return DocumentBlock(
        id=ident, text=text, page_index=page, kind=kind, font_size=font_size,
        bbox=(50, 25, 170, 40) if top else (290, 765, 310, 780),
    )


def test_short_repeated_dialogue_in_margin_is_not_deleted():
    examples = ("Yes.", "No!", "Why?", "Well…", "- Go", "− Stop")
    for text in examples:
        items = [block(page, text, ident=f"{page}") for page in range(3)]
        edits = pagination_cleanup(items, [PAGE] * 3, Pdf())
        assert not edits, f"deleted repeated substantive dialogue: {text}"


def test_quoted_standalone_numbers_and_list_markers_are_safe():
    for text, kind in (('"42"', "paragraph"), ("‘IV’", "paragraph"),
                       ("1)", "list"), ("3.", "list"), ("IV", "heading")):
        items = [block(page, text, ident=f"{page}", kind=kind) for page in range(3)]
        assert not pagination_cleanup(items, [PAGE] * 3, Pdf())


def test_known_running_header_still_removed_and_toggle_respected():
    items = [block(page, "Book Title", ident=f"h{page}") for page in range(3)]
    edits = pagination_cleanup(items, [PAGE] * 3, Pdf())
    assert {edit.block_id for edit in edits} == {"h0", "h1", "h2"}
    assert all(edit.accepted and edit.original == "Book Title" for edit in edits)
    assert not pagination_cleanup(items, [PAGE] * 3, Pdf(remove_headers=False))


def test_sequential_arabic_folios_are_still_removed():
    items = [
        block(page, str(page + 1), ident=f"folio{page}", top=False)
        for page in range(3)
    ]
    edits = pagination_cleanup(items, [PAGE] * 3, Pdf())
    assert {edit.block_id for edit in edits} == {"folio0", "folio1", "folio2"}
    assert not pagination_cleanup(items, [PAGE] * 3, Pdf(remove_page_numbers=False))

@pytest.mark.parametrize(
    "quoted", [
        "«Stay here»", "‹Stay here›", "„Stay here“",
        "‚Stay here‘", "「Stay here」", "『Stay here』", "《Stay here》",
    ],
)
def test_international_quotation_marks_protect_repeated_margin_prose(quoted):
    blocks = []
    for page in range(3):
        blocks.extend([
            block(page, quoted, ident=f"quote{page}"),
            DocumentBlock(
                id=f"header{page}", text="Running Book Title",
                page_index=page, kind="unknown", font_size=10,
                bbox=(240, 55, 355, 70),
            ),
        ])
    edits = pagination_cleanup(blocks, [PAGE] * 3, Pdf())
    assert {edit.block_id for edit in edits} == {
        f"header{page}" for page in range(3)
    }
    assert all(edit.original == "Running Book Title" for edit in edits)
