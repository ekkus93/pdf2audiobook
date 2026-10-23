"""Footnote narration placement: end of chapter or after the anchoring paragraph."""

import pytest

from pdf2audiobook.document.structure import place_footnotes, reflow_narration_lines
from pdf2audiobook.models import DocumentBlock


def block(index, text, *, page=0, kind="unknown", x=72):
    top = 100 + index * 12
    return DocumentBlock(
        id=f"b{index}",
        page_index=page,
        text=text,
        kind=kind,
        bbox=(x, top, 400, top + 10),
        order=index,
    )


def chapter():
    return [
        block(0, "The gods of the Roman and the Barbarian were"),
        block(1, "readily identified in every part of the world.5 So"),
        block(2, "the cults spread from province to province."),
        block(3, "A new paragraph about trade.", x=90),
        block(4, "5 See for instance, Caesar de Bell. Gall. vi. 17.", kind="footnote"),
        block(5, "Within a century the Gauls themselves applied", kind="footnote"),
        block(6, "9 A note whose anchor is not on this page.", kind="footnote"),
    ]


def test_inline_moves_note_after_its_anchoring_paragraph():
    ordered, relocated, kept = place_footnotes(chapter(), "inline")
    assert [b.id for b in ordered] == ["b0", "b1", "b2", "b4", "b5", "b3", "b6"]
    assert (relocated, kept) == (1, 1)
    spoken = reflow_narration_lines(ordered).split("\n\n")
    assert spoken[0].endswith("from province to province.")
    assert spoken[1].startswith("5 See for instance")


def test_end_moves_every_note_after_the_chapter_body():
    ordered, relocated, kept = place_footnotes(chapter(), "end")
    assert [b.id for b in ordered] == ["b0", "b1", "b2", "b3", "b4", "b5", "b6"]
    assert (relocated, kept) == (3, 0)


@pytest.mark.parametrize("policy", ["warn", "omit"])
def test_other_policies_keep_pdf_order(policy):
    blocks = chapter()
    ordered, relocated, kept = place_footnotes(blocks, policy)
    assert ordered == blocks and (relocated, kept) == (0, 3)


def test_ambiguous_or_other_page_anchors_keep_pdf_position():
    blocks = [
        block(0, "First mention of the matter.2 And"),
        block(1, "a second mention of it.2 Finally"),
        block(2, "2 Which mention this note belongs to is unclear.", kind="footnote"),
        block(3, "Next page prose with its own claim.3", page=1),
        block(4, "3 Note printed on the earlier page.", kind="footnote"),
    ]
    ordered, relocated, kept = place_footnotes(blocks, "inline")
    assert [b.id for b in ordered] == ["b0", "b1", "b2", "b3", "b4"]
    assert (relocated, kept) == (0, 2)


def test_placement_is_a_permutation_of_the_chapter():
    blocks = chapter()
    for policy in ("inline", "end"):
        ordered, _, _ = place_footnotes(blocks, policy)
        assert sorted(b.id for b in ordered) == sorted(b.id for b in blocks)
