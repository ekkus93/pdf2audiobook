"""Malformed source-box geometry cannot justify pagination deletion or reflow."""

import math

import pytest

from pdf2audiobook.config import Pdf
from pdf2audiobook.document.structure import pagination_cleanup, reflow_narration_lines
from pdf2audiobook.models import DocumentBlock


def _block(page: int, text: str, box=(280.0, 760.0, 320.0, 772.0)):
    return DocumentBlock(
        id=f"p{page}-{text}", page_index=page, text=text,
        bbox=box, font_size=11.0,
    )


@pytest.mark.parametrize(
    "bad_box",
    [
        (280.0, 760.0, math.nan, 772.0),
        (280.0, 760.0, math.inf, 772.0),
        (280.0, 760.0, 279.0, 772.0),
        (280.0, 760.0, 320.0, 750.0),
        ("untrusted", 760.0, 320.0, 772.0),
        (280.0, 760.0, 320.0),
        (True, 760.0, 320.0, 772.0),
    ],
)
def test_bad_candidate_bbox_never_removes_folio(bad_box):
    pages = [_block(page, str(page + 1)) for page in range(3)]
    # Exercise corrupted intermediate objects that bypass normal model parsing.
    pages[1] = pages[1].model_copy(update={"bbox": bad_box})
    assert pagination_cleanup(pages, [(600.0, 800.0)] * 3, Pdf()) == []
    assert [page.text for page in pages] == ["1", "2", "3"]


@pytest.mark.parametrize(
    "bad_box",
    [
        (0.0, math.nan, 20.0, 30.0),
        (0.0, 0.0, math.inf, 30.0),
        (0.0, 0.0, -1.0, 30.0),
        ("corrupt", 0.0, 20.0, 30.0),
        (0.0, 0.0, 20.0),
    ],
)
def test_bad_neighbor_bbox_is_not_used_for_body_proximity(bad_box):
    pages = [_block(page, str(page + 1)) for page in range(3)]
    neighbor = _block(1, "Unrelated text").model_copy(update={"bbox": bad_box})
    edits = pagination_cleanup(pages + [neighbor], [(600.0, 800.0)] * 3, Pdf())
    assert {edit.block_id for edit in edits} == {page.id for page in pages}


def test_invalid_reflow_bbox_preserves_separate_lines():
    first = _block(0, "First prose line", (60.0, 100.0, 200.0, 114.0))
    second = _block(0, "Second prose line", (60.0, 115.0, 200.0, 129.0))
    assert reflow_narration_lines([first, second]) == "First prose line Second prose line\n"
    invalid = first.model_copy(update={"bbox": (60.0, 100.0, math.inf, 114.0)})
    assert reflow_narration_lines([invalid, second]) == (
        "First prose line\n\nSecond prose line\n"
    )
