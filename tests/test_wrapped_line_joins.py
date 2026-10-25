"""Wrapped lines join unless a real list marker or a list end intervenes (R67)."""

from pdf2audiobook.document.structure import reflow_narration_lines
from pdf2audiobook.models import DocumentBlock


def block(index, text, *, kind="unknown", left=72, size=11.0, top=None):
    top = 100 + index * 14 if top is None else top
    return DocumentBlock(
        id=f"b{index}",
        span_ids=[],
        text=text,
        page_index=0,
        bbox=(left, top, 400, top + 12),
        order=index,
        kind=kind,
        font_size=size,
    )


def test_wrapped_line_starting_with_an_initial_joins():
    lines = [block(0, "The result was reported by"), block(1, "J. Smith of the Times.")]
    assert reflow_narration_lines(lines) == "The result was reported by J. Smith of the Times.\n"


def test_wrapped_line_starting_with_a_year_and_paren_joins():
    lines = [block(0, "It lasted from 1985 to"), block(1, "1990) was the later date.")]
    assert reflow_narration_lines(lines) == "It lasted from 1985 to 1990) was the later date.\n"


def test_real_list_markers_still_start_new_lines():
    lines = [block(0, "Steps:"), block(1, "1. First"), block(2, "2. Second")]
    assert reflow_narration_lines(lines) == "Steps:\n\n1. First\n\n2. Second\n"


def test_wrapped_continuation_of_a_list_item_joins_the_item():
    lines = [
        block(0, "1. The first item runs", kind="list"),
        block(1, "onto a second line.", left=84),
        block(2, "2. The second item.", kind="list"),
    ]
    assert reflow_narration_lines(lines) == (
        "1. The first item runs onto a second line.\n\n2. The second item.\n"
    )


def test_list_ends_at_an_outdented_body_paragraph():
    lines = [
        block(0, "1. First item.", kind="list", left=90),
        block(1, "2. Second item.", kind="list", left=90),
        block(2, "The body paragraph begins here.", left=72),
    ]
    assert reflow_narration_lines(lines) == (
        "1. First item.\n\n2. Second item.\n\nThe body paragraph begins here.\n"
    )


def test_list_ends_at_a_font_change():
    lines = [
        block(0, "1. First item.", kind="list", size=10.0),
        block(1, "2. Second item.", kind="list", size=10.0),
        block(2, "The body paragraph begins here.", size=12.0),
    ]
    assert reflow_narration_lines(lines) == (
        "1. First item.\n\n2. Second item.\n\nThe body paragraph begins here.\n"
    )
