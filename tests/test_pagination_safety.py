"""Fail-closed margin cleanup for legitimate prose and list markers."""
from __future__ import annotations

from pdf2audiobook.config import Pdf
from pdf2audiobook.document.structure import pagination_cleanup
from pdf2audiobook.models import DocumentBlock


def line(number: int, page: int, text: str, *, x: float, y: float,
         kind: str = "unknown") -> DocumentBlock:
    return DocumentBlock(
        id=f"b{number}", span_ids=[], page_index=page, text=text,
        bbox=(x, y, x + max(7, len(text) * 6), y + 12),
        order=number, kind=kind,
    )


def test_sequential_page_numbers_centered_are_removed():
    blocks = [
        line(1, 0, "1", x=295, y=800),
        line(2, 0, "Chapter 1", x=75, y=120, kind="heading"),
        line(3, 1, "2", x=295, y=800),
        line(4, 1, "Second page prose.", x=75, y=120),
    ]
    edits = pagination_cleanup(blocks, [(595, 842)] * 2, Pdf())
    assert {e.block_id for e in edits if e.accepted} == {"b1", "b3"}


def test_sequential_numbered_list_markers_are_preserved():
    blocks = [
        line(1, 0, "1", x=75, y=65),
        line(2, 0, "The first list item.", x=95, y=85),
        line(3, 1, "2", x=75, y=65),
        line(4, 1, "The second list item.", x=95, y=85),
    ]
    assert pagination_cleanup(blocks, [(595, 842)] * 2, Pdf()) == []


def test_repeated_quotes_and_headings_in_margin_are_preserved():
    blocks = [
        line(1, 0, "“1”", x=290, y=65),
        line(2, 1, "“1”", x=290, y=65),
        line(3, 0, "Chapter 1", x=75, y=60, kind="heading"),
        line(4, 1, "Chapter 1", x=75, y=60, kind="heading"),
    ]
    assert pagination_cleanup(blocks, [(595, 842)] * 2, Pdf()) == []


def test_repeated_running_footer_still_removed():
    blocks = [
        line(1, 0, "An Example Book", x=200, y=800),
        line(2, 1, "An Example Book", x=200, y=800),
    ]
    edits = pagination_cleanup(blocks, [(595, 842)] * 2, Pdf())
    assert {e.block_id for e in edits if e.accepted} == {"b1", "b2"}
