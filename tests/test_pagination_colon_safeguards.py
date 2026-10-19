"""Conservative running-header detection must preserve repeated substantive labels."""

import pytest

from pdf2audiobook.config import Pdf
from pdf2audiobook.document.structure import pagination_cleanup
from pdf2audiobook.models import DocumentBlock


def _margin_blocks(text, band):
    top = 20.0 if band == "header" else 760.0
    return [
        DocumentBlock(
            id=f"p{page}", page_index=page, text=text,
            bbox=(40.0, top, 205.0, top + 12.0),
        )
        for page in range(3)
    ]


@pytest.mark.parametrize("band", ["header", "footer"])
@pytest.mark.parametrize("text", ["The narrator:", "John 3:16", "Scene Two："])
def test_repeated_dialogue_labels_and_numeric_citations_are_not_removed(band, text):
    blocks = _margin_blocks(text, band)
    edits = pagination_cleanup(blocks, [(600.0, 800.0)] * 3, Pdf())
    assert edits == []
    assert [block.text for block in blocks] == [text] * 3


@pytest.mark.parametrize("band", ["header", "footer"])
def test_real_repeated_running_title_still_removed(band):
    blocks = _margin_blocks("A Study of Light", band)
    edits = pagination_cleanup(blocks, [(600.0, 800.0)] * 3, Pdf())
    assert {edit.block_id for edit in edits} == {block.id for block in blocks}
    assert all(edit.accepted and edit.replacement == "" for edit in edits)
