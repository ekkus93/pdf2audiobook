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


def _line(index, text, bbox, size=10.0):
    return DocumentBlock(
        id=f"t{index}", span_ids=[], text=text, page_index=0, bbox=bbox, order=index,
        kind="unknown", font_size=size,
    )  # fmt: skip


def test_line_made_tall_by_a_radical_joins_the_line_above():
    # Geometry from "Attention Is All You Need", page 4: the radical's box overlaps the line above.
    lines = [
        _line(0, "We compute the dot products of the", (108.0, 380.5, 504.0, 391.3)),
        _line(1, "query with all keys, divide each by √dk, and", (108.0, 383.5, 504.0, 402.2)),
        _line(2, "values.", (107.8, 402.5, 135.4, 412.5)),
    ]
    assert reflow_narration_lines(lines) == (
        "We compute the dot products of the query with all keys, divide each by √dk, and values.\n"
    )


def test_fraction_split_line_and_the_line_after_it_join():
    lines = [
        _line(0, "The two attention functions are", (107.7, 499.5, 505.7, 509.5)),
        _line(1, "identical, except for the scaling factor", (108.0, 510.4, 504.2, 520.4)),
        _line(2, "of 1", (108.0, 519.5, 129.6, 531.3)),
        _line(3, "√dk . Additive attention uses a network with", (120.1, 521.3, 504.0, 536.6)),
        _line(4, "a single hidden layer.", (108.0, 534.4, 504.0, 544.5)),
    ]
    assert reflow_narration_lines(lines) == (
        "The two attention functions are identical, except for the scaling factor of 1 over √dk . Additive attention uses a network"
        " with a single hidden layer.\n"
    )


def test_equation_number_and_indented_paragraph_stay_apart_from_a_tall_line():
    lines = [
        _line(0, "Attention(Q, K, V ) = softmax(QKT )V", (220.0, 465.0, 389.8, 482.9)),
        _line(1, "(1)", (493.1, 473.2, 504.7, 483.2)),
        _line(2, "divide each by √dk to finish.", (108.0, 600.0, 504.0, 618.0)),
        _line(3, "An indented new paragraph.", (124.0, 611.0, 504.0, 621.0)),
    ]
    assert reflow_narration_lines(lines) == (
        "Attention(Q, K, V ) = softmax(QKT )V\n\n(1)\n\ndivide each by √dk to finish.\n\n"
        "An indented new paragraph.\n"
    )


def test_padded_epub_line_boxes_keep_paragraph_breaks():
    # Geometry from the golden EPUB: 11-pt text in 16-pt line boxes that overlap.
    lines = [
        _line(0, "Paragraph 1 continues with plain", (33.0, 127.5, 366.2, 143.6), 11.0),
        _line(1, "narrative prose so that several", (33.0, 140.7, 313.2, 156.8), 11.0),
        _line(2, "paragraphs fill a page.", (33.0, 153.9, 141.9, 170.0), 11.0),
        _line(3, "Paragraph 2 of the invented passage", (33.0, 178.1, 322.3, 194.2), 11.0),
        _line(4, "continues here.", (33.0, 191.3, 322.3, 207.4), 11.0),
    ]
    assert reflow_narration_lines(lines) == (
        "Paragraph 1 continues with plain narrative prose so that several paragraphs fill a"
        " page.\n\nParagraph 2 of the invented passage continues here.\n"
    )


def test_inline_fraction_at_a_line_end_reads_over():
    lines = [
        _line(
            0, "the dot products grow large in magnitude, pushing the", (108.0, 594.3, 504.0, 605.1)
        ),
        _line(1, "this effect, we scale the dot products by 1", (108.0, 603.6, 450.2, 615.4)),
        _line(2, "√dk .", (440.7, 605.4, 459.5, 620.7)),
    ]
    assert reflow_narration_lines(lines) == (
        "the dot products grow large in magnitude, pushing the this effect, we scale the dot"
        " products by 1 over √dk .\n"
    )


def test_text_continuing_after_a_short_word_is_not_a_fraction():
    # The next piece starts after the word ends, so nothing sits under it.
    lines = [
        _line(0, "Consider the case where", (108.0, 589.0, 504.0, 599.0)),
        _line(1, "the value of x is", (108.0, 600.0, 180.0, 610.0)),
        _line(2, "√2 . Then", (182.0, 598.0, 504.0, 615.0)),
    ]
    assert reflow_narration_lines(lines) == "Consider the case where the value of x is √2 . Then\n"
