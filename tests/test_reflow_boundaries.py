"""Preserve dialogue, scene breaks, lists and headings during safe PDF reflow."""
from pdf2audiobook.document.structure import reflow_narration_lines
from pdf2audiobook.models import DocumentBlock


def block(index: int, text: str, *, kind: str = "unknown") -> DocumentBlock:
    top = 100 + index * 14
    return DocumentBlock(
        id=f"b{index}", span_ids=[], text=text, page_index=0,
        bbox=(72, top, 400, top + 12), order=index, kind=kind,
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
        "The room was quiet.", "“Who is there?”", "— Someone replied.",
        "* * *", "The next scene began.\n",
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
