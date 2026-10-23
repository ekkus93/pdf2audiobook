"""Running heads that share a line with the folio (real-scan regressions, synthetic text).

Modelled on an Internet Archive scan of a public-domain history (historyofdecl01gibb):
alternating "TITLE 27" / "30 OTHER TITLE" heads in large type directly above body
text, a separately extracted folio beside a title, and a heading-styled section
title repeated on every page of that section.
"""

from pdf2audiobook.config import Pdf
from pdf2audiobook.document.structure import pagination_cleanup
from pdf2audiobook.models import DocumentBlock

SIZE = (326, 505)


def block(page, name, text, x0, y0, x1, y1, *, size=8.6, kind="unknown"):
    return DocumentBlock(
        id=f"p{page}-{name}",
        page_index=page,
        text=text,
        kind=kind,
        bbox=(x0, y0, x1, y1),
        font_size=size,
    )


def body(page, y=47):
    return block(
        page, "body", f"ordinary prose line on page {page} continues here", 18, y, 281, y + 9
    )


def removed(blocks, pages):
    return {
        edit.block_id: edit.reason for edit in pagination_cleanup(blocks, [SIZE] * pages, Pdf())
    }


def test_alternating_heads_with_embedded_folios_are_removed():
    blocks = []
    for page in range(6):
        folio = page + 27
        head = f"OF THE EMPIRE {folio}" if page % 2 == 0 else f"{folio} THE HISTORY"
        # Large type, 7pt above the first body line: the margin is tight.
        blocks += [block(page, "head", head, 63, 23, 284, 40, size=17), body(page)]
    result = removed(blocks, 6)
    assert set(result) == {f"p{page}-head" for page in range(6)}
    assert set(result.values()) == {"repeated running header with page number"}
    assert not any(name.endswith("body") for name in result)


def test_separate_folio_beside_running_title_is_sequenced_by_embedded_folios():
    blocks = []
    for page in range(7):
        folio = page + 27
        if page == 1:
            blocks += [
                block(page, "folio", "28", 44, 15, 58, 28, size=11),
                block(page, "head", "THE HISTORY", 93, 18, 257, 31, size=14),
            ]
        else:
            head = f"OF THE EMPIRE {folio}" if page % 2 == 0 else f"{folio} THE HISTORY"
            blocks.append(block(page, "head", head, 63, 18, 278, 31, size=17))
        blocks.append(body(page, 60))
    result = removed(blocks, 7)
    assert result["p1-folio"] == "sequential/repeated page number"
    assert result["p1-head"] == "repeated running header"


def test_heading_styled_section_title_repeated_as_running_head():
    blocks = [
        # The section's own title once, in the body region of its first page.
        block(0, "title", "INTRODUCTION", 120, 120, 200, 134, size=16, kind="heading"),
        body(0, 150),
    ]
    for page in range(1, 5):
        blocks += [
            block(page, "head", "INTRODUCTION", 136, 14, 235, 27, size=14, kind="heading"),
            body(page),
        ]
    result = removed(blocks, 5)
    assert set(result) == {f"p{page}-head" for page in range(1, 5)}
    assert "p0-title" not in result


def test_formula_fragments_in_margins_are_not_running_heads():
    blocks = []
    for page in range(4):
        blocks += [
            block(page, "formula", "x dx", 140, 460, 170, 470),
            block(page, "body", "ordinary prose about integration", 18, 200, 281, 209),
        ]
    assert removed(blocks, 4) == {}


def test_chapter_label_in_header_keeps_its_numeral():
    blocks = []
    for page, label in enumerate(("CHAPTER I", "CHAPTER II", "CHAPTER III")):
        blocks += [
            block(page, "label", label, 120, 20, 200, 34, size=16, kind="heading"),
            body(page),
        ]
    assert removed(blocks, 3) == {}
