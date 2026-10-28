"""Corroborated numerals suppress headings supported only by font size (F3)."""

from pdf2audiobook.config import Settings
from pdf2audiobook.document.structure import propose_chapters
from pdf2audiobook.models import DocumentBlock

PROSE = "Ordinary narrative prose that continues for a while on this page of the book."
STRAY = "A Stray Display Line"


def _block(i: int, page: int, text: str, size: float = 11.0) -> DocumentBlock:
    return DocumentBlock(id=f"b{i}", page_index=page, text=text, kind="paragraph", font_size=size)


def _numeral_book(*, stray: bool = True, contents: bool = True):
    """Contents list, then numeral chapters of varying length; one large-type line in chapter 3."""
    blocks = []
    if contents:
        blocks = [_block(i, 0, f"Chapter {i}") for i in range(1, 9)]
    k, page = 100, 1
    for number, pages in enumerate([2, 3, 2, 3, 2, 3, 2, 3], start=1):
        blocks += [_block(k, page, str(number)), _block(k + 1, page, PROSE)]
        k += 2
        if stray and number == 3:
            blocks.append(_block(k, page + 1, STRAY, size=22.0))
            k += 1
        for extra in range(1, pages):
            blocks.append(_block(k, page + extra, PROSE))
            k += 1
        page += pages
    return blocks


def _plan(blocks):
    settings = Settings().chapters.model_copy(update={"allow_single_chapter": True})
    return propose_chapters(blocks, set(), [], settings)


def test_a_large_type_line_inside_a_numeral_book_is_not_a_chapter() -> None:
    proposal = _plan(_numeral_book())
    titles = [c.title for c in proposal.chapters]
    assert STRAY not in titles
    assert [t for t in titles if t.startswith("Chapter")] == [f"Chapter {n}" for n in range(1, 9)]
    assert any("Ignored 1 font-size-only heading candidate" in w for w in proposal.warnings)


def test_the_stray_line_would_split_the_book_without_the_gate() -> None:
    # Control: the same line is a real heading when nothing else gives strong evidence.
    blocks = [_block(0, 0, PROSE), _block(1, 0, STRAY, size=22.0)]
    blocks += [_block(i, 1, PROSE) for i in range(2, 8)]
    assert STRAY in [c.title for c in _plan(blocks).chapters]


def test_a_numeral_book_without_stray_type_has_no_warning() -> None:
    proposal = _plan(_numeral_book(stray=False))
    assert not any("font-size-only" in w for w in proposal.warnings)


def test_without_corroborated_numerals_typographic_headings_still_work() -> None:
    blocks, k = [], 0
    for page, title in enumerate(["First Title", "Second Title", "Third Title"]):
        blocks += [_block(k, page, title, size=22.0), _block(k + 1, page, PROSE)]
        blocks += [_block(k + 2, page, PROSE), _block(k + 3, page, PROSE)]
        k += 4
    titles = [c.title for c in _plan(blocks).chapters]
    assert {"First Title", "Second Title", "Third Title"} <= set(titles)
