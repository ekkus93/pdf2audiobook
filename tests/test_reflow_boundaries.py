"""Preserve dialogue, scene breaks, lists and headings during safe PDF reflow."""

from pdf2audiobook.document.structure import reflow_narration_lines
from pdf2audiobook.models import DocumentBlock


def block(index: int, text: str, *, kind: str = "unknown") -> DocumentBlock:
    top = 100 + index * 14
    return DocumentBlock(
        id=f"b{index}",
        span_ids=[],
        text=text,
        page_index=0,
        bbox=(72, top, 400, top + 12),
        order=index,
        kind=kind,
    )


def test_soft_wrap_reflows_without_changing_source():
    original = [block(0, "The first part of a"), block(1, "single long sentence.")]
    before = [b.text for b in original]
    assert reflow_narration_lines(original) == "The first part of a single long sentence.\n"
    assert [b.text for b in original] == before


def test_dialogue_and_scene_markers_stay_separate():
    lines = [
        block(0, "The room was quiet."),
        block(1, "“Who is there?”"),
        block(2, "— Someone replied."),
        block(3, "* * *"),
        block(4, "The next scene began."),
    ]
    result = reflow_narration_lines(lines)
    assert result.split("\n\n") == [
        "The room was quiet.",
        "“Who is there?”",
        "— Someone replied.",
        "* * *",
        "The next scene began.\n",
    ]


def test_list_and_special_blocks_do_not_join_prose():
    lines = [
        block(0, "Instructions:"),
        block(1, "1. First item"),
        block(2, "- Second item"),
        block(3, "Section Title", kind="heading"),
        block(4, "Next paragraph starts here."),
        block(5, "continued on the next line."),
    ]
    text = reflow_narration_lines(lines)
    assert text == (
        "Instructions:\n\n1. First item\n\n- Second item\n\n"
        "Section Title\n\nNext paragraph starts here. continued on the next line.\n"
    )


def test_ascii_hyphen_preserved_when_wrapped():
    lines = [block(0, "well-"), block(1, "being matters.")]
    assert reflow_narration_lines(lines) == "well-being matters.\n"


def test_unicode_soft_hyphen_is_repaired_only_across_soft_wrap():
    lines = [block(0, "inter\u00ad"), block(1, "national cooperation.")]
    assert reflow_narration_lines(lines) == "international cooperation.\n"


def test_indented_paragraph_stays_separate():
    first = block(0, "The previous paragraph ends.")
    second = block(1, "A new paragraph begins.")
    second.bbox = (110, 114, 400, 126)
    assert reflow_narration_lines([first, second]) == (
        "The previous paragraph ends.\n\nA new paragraph begins.\n"
    )


def test_page_boundary_stays_separate_even_if_geometry_matches():
    first = block(0, "Last line of page one.")
    second = block(1, "First line of page two.")
    second.page_index = 1
    assert reflow_narration_lines([first, second]) == (
        "Last line of page one.\n\nFirst line of page two.\n"
    )


def test_large_vertical_gap_stays_separate():
    first = block(0, "A short paragraph.")
    second = block(1, "Another paragraph.")
    second.bbox = (72, 160, 400, 172)
    assert reflow_narration_lines([first, second]) == ("A short paragraph.\n\nAnother paragraph.\n")


def _on_page(index: int, page: int, text: str, *, kind: str = "unknown") -> DocumentBlock:
    return block(index, text, kind=kind).model_copy(update={"page_index": page})


def test_sentence_continuing_over_a_page_break_is_one_paragraph():
    lines = [
        _on_page(0, 0, "poems as Tennyson's In the Valley, Meredith's Love in"),
        _on_page(1, 0, "22"),  # removed folio
        _on_page(2, 1, "the Valley, and Kipling's Last Chantey explained."),
    ]
    assert reflow_narration_lines(lines, {"b1": ""}) == (
        "poems as Tennyson's In the Valley, Meredith's Love in "
        "the Valley, and Kipling's Last Chantey explained.\n"
    )


def test_page_break_keeps_paragraphs_that_end_or_restart():
    ended = [_on_page(0, 0, "The chapter closes here."), _on_page(1, 1, "and then lowercase.")]
    capital = [_on_page(0, 0, "a line without a stop"), _on_page(1, 1, "The next paragraph.")]
    skipped = [_on_page(0, 0, "a line without a stop"), _on_page(1, 2, "lowercase two pages on.")]
    note = [_on_page(0, 0, "a line without a stop"), _on_page(1, 1, "a note", kind="footnote")]
    for lines in (ended, capital, skipped, note):
        assert reflow_narration_lines(lines).count("\n\n") == 1
