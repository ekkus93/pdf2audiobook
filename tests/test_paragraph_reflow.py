from pdf2audiobook.document.structure import reflow_narration_lines
from pdf2audiobook.models import DocumentBlock


def make_block(
    ident: str, text: str, y: float, *, x: float = 60, kind: str = "paragraph"
) -> DocumentBlock:
    return DocumentBlock(
        id=ident,
        text=text,
        page_index=0,
        bbox=(x, y, x + 200, y + 11),
        kind=kind,
    )


def test_soft_line_wraps_preserve_paragraphs_and_headings():
    blocks = [
        make_block("h", "Chapter 1", 45, kind="heading"),
        make_block("a", "This sentence continues", 95),
        make_block("b", "across another PDF line.", 109),
        make_block("c", "Next indented paragraph.", 137, x=80),
    ]
    spoken = reflow_narration_lines(blocks)
    assert spoken == (
        "Chapter 1\n\nThis sentence continues across another PDF line.\n\n"
        "Next indented paragraph.\n"
    )
    assert all(block.text != "This sentence continues across another PDF line." for block in blocks)


def test_reflow_does_not_join_dialogue_or_compound_hyphens():
    blocks = [
        make_block("a", "A well-", 100),
        make_block("b", "known expression.", 114),
        make_block("c", '"A new speaker," she said.', 128),
    ]
    assert reflow_narration_lines(blocks) == (
        'A well-known expression.\n\n"A new speaker," she said.\n'
    )


def test_soft_hyphen_and_audited_edits():
    blocks = [
        make_block("a", "the soft\u00ad", 100),
        make_block("b", "ware works.", 114),
    ]
    assert reflow_narration_lines(blocks) == "the software works.\n"
    assert reflow_narration_lines(blocks, {"b": "ware is working."}) == (
        "the software is working.\n"
    )
