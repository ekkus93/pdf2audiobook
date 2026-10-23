"""Pagination cleanup fails closed on malformed page geometry."""

import math

import pytest

from pdf2audiobook.config import Pdf
from pdf2audiobook.document.structure import pagination_cleanup
from pdf2audiobook.models import DocumentBlock


def folio(page: int) -> DocumentBlock:
    return DocumentBlock(
        id=f"folio-{page + 1}",
        span_ids=[f"folio-{page + 1}"],
        text=str(page + 1),
        page_index=page,
        kind="unknown",
        bbox=(295.0, 807.0, 305.0, 820.0),
        font_size=10.0,
    )


@pytest.mark.parametrize(
    "bad_dimensions",
    [
        (0, 842),
        (-1, 842),
        (math.nan, 842),
        (math.inf, 842),
        ("595", 842),
        (True, 842),
        (10**500, 842),
        (595, None),
        (595,),
        None,
        (),
        (595, 842, 0),
    ],
)
def test_bad_page_sizes_never_authorize_folio_removal(bad_dimensions):
    blocks = [folio(0), folio(1), folio(2)]
    sizes = [(595.0, 842.0), bad_dimensions, (595.0, 842.0)]
    assert pagination_cleanup(blocks, sizes, Pdf()) == []


def test_valid_page_sizes_still_recognize_sequential_folios():
    blocks = [folio(0), folio(1), folio(2)]
    sizes = [(595.0, 842.0)] * 3
    edits = pagination_cleanup(blocks, sizes, Pdf())
    assert {edit.block_id for edit in edits} == {block.id for block in blocks}
    assert all(edit.accepted and edit.replacement == "" for edit in edits)
