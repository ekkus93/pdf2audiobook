"""Malformed font metadata cannot create false chapter boundaries."""

import math

import pytest

from pdf2audiobook.config import Chapters
from pdf2audiobook.document.structure import propose_chapters
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.models import DocumentBlock


def paragraph(number: int, text: str, font_size: float) -> DocumentBlock:
    return DocumentBlock(
        id=f"p{number}",
        span_ids=[f"p{number}"],
        text=text,
        page_index=0,
        font_size=font_size,
        kind="paragraph",
    )


@pytest.mark.parametrize("corrupt_size", [math.inf, -math.inf, math.nan])
def test_nonfinite_font_size_never_creates_a_chapter(corrupt_size):
    blocks = [
        paragraph(1, "A normal first paragraph", 12.0),
        paragraph(2, "A normal second paragraph", 12.0),
        paragraph(3, "A normal third paragraph", 12.0),
        paragraph(4, "Ordinary unnumbered prose", corrupt_size),
    ]
    with pytest.raises(ExtractionError, match="No reliable chapter boundaries"):
        propose_chapters(blocks, set(), [], Chapters(allow_single_chapter=False))


def test_finite_typographic_contrast_still_creates_heading():
    blocks = [
        paragraph(1, "A normal first paragraph", 12.0),
        paragraph(2, "A normal second paragraph", 12.0),
        paragraph(3, "A normal third paragraph", 12.0),
        paragraph(4, "A Valid Unnumbered Heading", 20.0),
        paragraph(5, "Another normal paragraph", 12.0),
    ]
    chapters, warnings = propose_chapters(blocks, set(), [], Chapters(allow_single_chapter=False))
    assert [chapter.start_block for chapter in chapters] == [0, 3]
    assert chapters[1].title == "A Valid Unnumbered Heading"
    assert chapters[1].evidence == ["typographic size contrast with body text"]
    assert any("front-matter" in warning for warning in warnings)
