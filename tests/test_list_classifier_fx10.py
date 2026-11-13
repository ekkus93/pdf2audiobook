"""List classification and reflow edge cases from the fourth review."""

import pytest

from pdf2audiobook.document.listing import is_list_line
from pdf2audiobook.document.structure import (
    footnote_anchor_edits,
    footnote_omit_edits,
    reflow_narration_lines,
)
from pdf2audiobook.models import DocumentBlock
from pdf2audiobook.pdf import _build_page_blocks, _footnote_line_indices


def _line(text: str, y: float, *, size: float = 12, x: float = 50) -> dict:
    return {"text": text, "bbox": (x, y, x + 300, y + 12), "size": size}


def _blocks(lines: list[dict], *, footnotes: set[int] | None = None) -> list[DocumentBlock]:
    _, blocks = _build_page_blocks(
        lines,
        page_index=0,
        page_label="1",
        origin="embedded",
        order_offset=0,
        table_regions=[],
        footnote_indices=footnotes or set(),
        caption_indices=set(),
        equation_indices=set(),
    )
    return blocks


def test_sequential_numbered_footnotes_remain_footnotes_and_are_omittable():
    lines = [
        _line("Ordinary body paragraph one.", 100),
        _line("Ordinary body paragraph two.", 130),
        _line("1. First source note.", 730, size=7),
        _line("2. Second source note.", 750, size=7),
    ]
    footnote_indices = _footnote_line_indices(lines, page_height=800, table_regions=[])
    blocks = _blocks(lines, footnotes=footnote_indices)

    assert footnote_indices == {2, 3}
    assert [blocks[index].kind for index in sorted(footnote_indices)] == ["footnote", "footnote"]
    assert not footnote_anchor_edits(blocks, set())
    omit_edits = footnote_omit_edits(blocks)
    assert {edit.block_id for edit in omit_edits} == {blocks[2].id, blocks[3].id}
    omitted = {edit.block_id: edit.replacement for edit in omit_edits}
    narration = reflow_narration_lines(blocks, omitted)
    assert "First source note" not in narration
    assert "Second source note" not in narration


def test_consecutive_capitalized_initials_are_one_prose_paragraph():
    blocks = _blocks(
        [
            _line("A. Smith attended the meeting,", 100),
            _line("B. Jones took notes.", 115),
        ]
    )

    assert [block.kind for block in blocks] == ["unknown", "unknown"]
    assert reflow_narration_lines(blocks) == "A. Smith attended the meeting, B. Jones took notes.\n"


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("The meeting was held in May", "12. Then he left the room."),
        ("The evidence appears on page", "42) and later in the appendix."),
    ],
)
def test_wrapped_numeric_text_joins_when_marker_is_not_a_list(first, second):
    blocks = _blocks([_line(first, 100), _line(second, 115)])

    assert reflow_narration_lines(blocks) == f"{first} {second}\n"


def test_body_line_at_list_marker_margin_starts_a_new_paragraph():
    blocks = _blocks(
        [
            _line("1. First item.", 100),
            _line("2. Second item.", 115),
            _line("The body paragraph begins here.", 130),
        ]
    )

    narration = reflow_narration_lines(blocks)
    assert "2. Second item.\n\nThe body paragraph begins here." in narration


# --- Marker rules (test coverage spec T6.b) ------------------------------------


PROSE = "An ordinary line of prose."


@pytest.mark.parametrize(
    ("previous", "line", "expected"),
    [
        ("a) first", "b) second", True),
        ("a) first", "c) third", False),
        ("B. first", "c. second", True),
        ("• first", "• second", True),
        ("* first", "* second", True),
        ("* first", "• second", False),
        ("1. first", "• second", False),
        ("i) first", "ii) second", True),
        ("iv) fourth", "v) fifth", True),
        ("ii) second", "iv) fourth", False),
        ("9. ninth", "10. tenth", True),
        ("9. ninth", "11. eleventh", False),
    ],
    ids=[
        "letters",
        "letters-skip",
        "letters-mixed-case",
        "bullets",
        "asterisks",
        "different-bullets",
        "number-then-bullet",
        "roman",
        "roman-iv-v",
        "roman-skip",
        "numbers",
        "numbers-skip",
    ],
)
def test_list_runs_need_sequential_markers(previous, line, expected):
    """T6.b: with neighbours present, only a continuing marker makes a list line."""
    assert is_list_line(line, previous_text=previous, next_text=PROSE) is expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [("25) items were counted", True), ("250) items were counted", False), ("250. Next", True)],
    ids=["two-digit-paren", "three-digit-paren", "three-digit-period"],
)
def test_three_digit_parenthesised_number_is_prose(line, expected):
    """T6.b: "250)" reads as a closing parenthesis after a number, not a list marker."""
    assert is_list_line(line) is expected


def test_bulleted_lines_become_list_blocks():
    """A run of matching bullets is a list during extraction, not unknown text."""
    blocks = _blocks(
        [
            _line("• Gather the tools.", 100),
            _line("• Read the manual.", 115),
            _line("• Start the engine.", 130),
        ]
    )

    assert [block.kind for block in blocks] == ["list", "list", "list"]
