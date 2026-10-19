"""Pagination classification must fail closed for malformed page geometry."""

import math

import pytest

from pdf2audiobook.config import Pdf
from pdf2audiobook.document.structure import pagination_cleanup
from pdf2audiobook.models import DocumentBlock


def _three_margin_lines(content):
    return [
        DocumentBlock(
            id=f"page-{number}", page_index=number,
            text=content[number] if isinstance(content, list) else content,
            bbox=(280.0, 760.0, 320.0, 772.0),
            font_size=11.0,
        )
        for number in range(3)
    ]


@pytest.mark.parametrize(
    "bad_geometry",
    [(0.0, 800.0), (600.0, 0.0), (-600.0, 800.0),
     (600.0, -800.0), (math.inf, 800.0),
     (600.0, math.nan)],
)
def test_invalid_page_geometry_does_not_trigger_cleanup_or_divide(bad_geometry):
    blocks = _three_margin_lines(["1", "2", "3"])
    sizes = [(600.0, 800.0), bad_geometry, (600.0, 800.0)]
    assert pagination_cleanup(blocks, sizes, Pdf()) == []
    assert [block.text for block in blocks] == ["1", "2", "3"]


def test_out_of_range_page_index_is_not_used_as_evidence():
    blocks = [
        DocumentBlock(
            id="invalid", page_index=1, text="A Study of Light",
            bbox=(100.0, 10.0, 220.0, 22.0),
        ),
        DocumentBlock(
            id="valid", page_index=0, text="A Study of Light",
            bbox=(100.0, 10.0, 220.0, 22.0),
        ),
    ]
    assert pagination_cleanup(blocks, [(600.0, 800.0)], Pdf()) == []


def test_valid_sequential_page_folios_still_removed():
    blocks = _three_margin_lines(["1", "2", "3"])
    edits = pagination_cleanup(blocks, [(600.0, 800.0)] * 3, Pdf())
    assert {edit.block_id for edit in edits} == {block.id for block in blocks}
    assert all(edit.accepted and edit.replacement == "" for edit in edits)
