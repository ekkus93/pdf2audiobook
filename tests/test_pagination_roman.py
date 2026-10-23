"""Adversarial pagination regression: preserve substantive text and Roman folios."""

from __future__ import annotations

from pdf2audiobook.config import Pdf
from pdf2audiobook.document.structure import pagination_cleanup
from pdf2audiobook.models import DocumentBlock


def margin_block(
    page: int, text: str, *, x: float = 290, y: float = 806, kind: str = "paragraph"
) -> DocumentBlock:
    return DocumentBlock(
        id=f"p{page}-{text}",
        text=text,
        page_index=page,
        kind=kind,
        bbox=(x, y, x + 15, y + 14),
    )


SIZES = [(600.0, 840.0)] * 10


def removed(blocks, settings=None):
    return {
        edit.block_id
        for edit in pagination_cleanup(blocks, SIZES, settings or Pdf())
        if edit.accepted and not edit.replacement
    }


def test_canonical_roman_folios_need_three_sequential_pages():
    folios = [margin_block(page, roman) for page, roman in enumerate(("i", "ii", "iii", "iv"))]
    assert removed(folios) == {b.id for b in folios}
    assert removed(folios[:2]) == set()
    assert removed([margin_block(0, "IC"), margin_block(1, "ID")]) == set()


def test_repeated_identical_numerals_not_sufficient_to_delete():
    repeated = [margin_block(p, "I") for p in range(4)]
    assert removed(repeated) == set()
    repeated_arabic = [margin_block(p, "1") for p in range(4)]
    assert removed(repeated_arabic) == set()


def test_arabic_folios_can_mirror_on_alternating_pages():
    folios = [margin_block(p, str(p + 12), x=12 if p % 2 == 0 else 570) for p in range(4)]
    assert removed(folios) == {b.id for b in folios}
    misaligned = [margin_block(0, "12", x=12), margin_block(1, "13", x=290)]
    assert removed(misaligned) == set()


def test_lists_quotes_and_substantive_prose_remain():
    lines = [
        margin_block(0, "1.", kind="list"),
        margin_block(1, "2.", kind="list"),
        margin_block(0, "“I”"),
        margin_block(1, "“II”"),
        margin_block(0, "This sentence is substantive prose, not a footer."),
        margin_block(1, "This sentence is substantive prose, not a footer."),
        margin_block(0, "Chapter I", kind="heading"),
        margin_block(1, "Chapter I", kind="heading"),
        margin_block(0, "1", kind="footnote"),
        margin_block(1, "2", kind="footnote"),
    ]
    assert removed(lines) == set()


def test_repeated_running_title_respects_toggle_and_numeral_toggle():
    titles = [margin_block(p, "Sample Book", y=12) for p in range(3)]
    numbers = [margin_block(p, str(p + 10)) for p in range(3)]
    assert removed(titles + numbers) == {b.id for b in titles + numbers}
    assert removed(titles + numbers, Pdf(remove_headers=False, remove_page_numbers=False)) == set()
    assert removed(titles + numbers, Pdf(remove_footers=False)) == {b.id for b in titles + numbers}


def test_same_line_list_continuation_and_large_roman_heading_are_preserved():
    entries = []
    for page, value in enumerate(("1", "2", "3")):
        entries.append(margin_block(page, value))
        entries.append(
            DocumentBlock(
                id=f"list-content-{page}",
                page_index=page,
                kind="paragraph",
                text="A substantive list item that must not be discarded.",
                bbox=(318, 806, 590, 820),
            )
        )
    assert removed(entries) == set()

    roman_titles = [
        DocumentBlock(
            id=f"roman-title-{page}",
            page_index=page,
            kind="unknown",
            text=roman,
            bbox=(290, 18, 305, 34),
            font_size=22,
        )
        for page, roman in enumerate(("I", "II", "III"))
    ]
    assert removed(roman_titles) == set()
