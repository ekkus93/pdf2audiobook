"""A research paper's chapters are its sections (chapter-detection-v6).

A 63-page paper with figure-heavy pages became 73 chapters: every numbered subsection opened
one, the body size was read from the figures' short lines (8 pt against a 10 pt body), and
"1 Introduction" was missed because arXiv's stamp, set vertically in the margin beside it,
counted as the line above it.
"""

from __future__ import annotations

from pdf2audiobook.config import Chapters
from pdf2audiobook.document.headings import _space_above, _typical_body_size
from pdf2audiobook.document.structure import propose_chapters
from pdf2audiobook.models import DocumentBlock


def line(
    index: int,
    text: str,
    *,
    page: int = 0,
    size: float = 10.0,
    bbox: tuple[float, float, float, float] | None = None,
) -> DocumentBlock:
    return DocumentBlock(
        id=f"b{index}",
        page_index=page,
        text=text,
        span_ids=[],
        order=index,
        kind="unknown",
        font_size=size,
        bbox=bbox,
    )


def prose(start: int, page: int, count: int = 3) -> list[DocumentBlock]:
    return [
        line(start + n, f"An ordinary sentence of body prose number {start + n}.", page=page)
        for n in range(count)
    ]


def test_numbered_subsections_stay_in_their_sections_chapter() -> None:
    blocks = [
        line(0, "2 Self-Rewriting", size=14),
        *prose(1, 0),
        line(4, "2.1 Problem Definition", page=1, size=14),
        *prose(5, 1),
        line(8, "2.2 The Session", page=2, size=14),
        *prose(9, 2),
        line(12, "3 Experiments", page=3, size=14),
        *prose(13, 3),
        line(16, "3.1.2 Further Details", page=4, size=14),
        *prose(17, 4),
    ]
    chapters, warnings = propose_chapters(blocks, set(), [], Chapters())
    assert [c.title for c in chapters] == ["2 Self-Rewriting", "3 Experiments"]
    assert "Kept 3 numbered subsection heading(s) inside their sections' chapters" in warnings


def test_appendix_subsections_stay_in_their_appendix() -> None:
    blocks = [
        line(0, "D Experimental Details", size=14),
        *prose(1, 0),
        line(4, "D.1 Settings of Every Session", page=1, size=14),
        *prose(5, 1),
    ]
    chapters, _ = propose_chapters(blocks, set(), [], Chapters())
    assert [c.title for c in chapters] == ["D Experimental Details"]


def test_subsections_without_a_section_heading_remain_chapters() -> None:
    # A book numbering its chapters "1.1", "1.2" with no "1" heading keeps them.
    blocks = [
        line(0, "1.1 The Harbour", size=14),
        *prose(1, 0),
        line(4, "1.2 The Storm", page=1, size=14),
        *prose(5, 1),
    ]
    chapters, _ = propose_chapters(blocks, set(), [], Chapters())
    assert [c.title for c in chapters] == ["1.1 The Harbour", "1.2 The Storm"]


def test_the_body_size_is_weighed_by_characters_not_lines() -> None:
    labels = [line(i, "x1", size=7.0) for i in range(10)]
    body = [
        line(10 + i, "A long line of ordinary body text set in the body size.", size=10.0)
        for i in range(4)
    ]
    assert _typical_body_size(labels + body, set()) == 10.0


def test_a_margin_stamp_beside_a_heading_is_not_above_it() -> None:
    blocks = [
        line(0, "Some text at the top of the page.", bbox=(70, 100, 500, 112)),
        # arXiv's identifier, set vertically in the left margin, reaching below the heading.
        line(1, "arXiv:2611.21885v2 [cs.AI] 18 Nov 2026", size=20, bbox=(24, 222, 44, 569)),
        line(2, "1 Introduction", size=14, bbox=(70, 558, 168, 572)),
    ]
    assert _space_above(blocks, 2, set()) == "gap"


def test_a_heading_at_the_top_of_the_second_column_has_space_above() -> None:
    blocks = [
        line(0, "The last line of the left column.", bbox=(50, 700, 290, 712)),
        line(1, "3 Experiments", size=14, bbox=(310, 80, 420, 94)),
    ]
    assert _space_above(blocks, 1, set()) == "gap"


def test_a_line_packed_under_the_one_above_is_still_tight() -> None:
    blocks = [
        line(0, "A line of advert copy.", size=18, bbox=(70, 100, 400, 120)),
        line(1, "Packed Display Line", size=18, bbox=(70, 121, 400, 141)),
    ]
    assert _space_above(blocks, 1, set()) == "tight"
