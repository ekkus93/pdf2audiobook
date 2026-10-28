"""Numeral chapter anchors follow the printed-to-physical page offset (F1)."""

from pdf2audiobook.config import Settings
from pdf2audiobook.document.structure import propose_chapters
from pdf2audiobook.models import DocumentBlock

PROSE = "Ordinary narrative prose that continues for a while on this page of the book."
OFFSET = 4
CHAPTERS = 5


def _block(i: int, page: int, text: str) -> DocumentBlock:
    return DocumentBlock(id=f"b{i}", page_index=page, text=text, kind="paragraph")


def _book(*, headings: tuple[str, ...] = ("Preface", "Prologue"), numerals: bool = True):
    """Front matter, named headings, then numeral chapters; returns (blocks, toc)."""
    blocks = [_block(i, page, PROSE) for i, page in enumerate(range(5))]  # pages 0-4
    toc: list[list] = []
    page, k = 5, 100
    for name in headings:
        blocks += [_block(k, page, name), _block(k + 1, page, PROSE)]
        toc.append([1, name, page + 1 - OFFSET])  # outline uses printed page numbers
        k, page = k + 2, page + 1
    for number in range(1, CHAPTERS + 1):
        first = str(number) if numerals else f"Interlude {number}"
        blocks += [
            _block(k, page, first),
            _block(k + 1, page, PROSE),
            _block(k + 2, page + 1, PROSE),
        ]
        toc.append([1, f"Chapter {number}", page + 1 - OFFSET])
        k, page = k + 3, page + 2
    return blocks, toc


def _plan(blocks, toc):
    settings = Settings().chapters.model_copy(update={"allow_single_chapter": True})
    return propose_chapters(blocks, set(), toc, settings)


def _anchored(proposal):
    return [c for c in proposal.chapters if "numbered chapter heading" in c.evidence[0]]


def test_numerals_are_anchored_through_the_inferred_offset() -> None:
    blocks, toc = _book()
    proposal = _plan(blocks, toc)
    chapters = _anchored(proposal)
    assert [c.title for c in chapters] == [f"Chapter {n}" for n in range(1, CHAPTERS + 1)]
    for number, chapter in enumerate(chapters, start=1):
        assert blocks[chapter.start_block].text == str(number)
    assert any("offset +4 inferred" in w for w in proposal.warnings)


def test_a_shifted_anchor_carries_the_alignment_warning_and_lower_confidence() -> None:
    blocks, toc = _book()
    proposal = _plan(blocks, toc)
    assert len(_anchored(proposal)) == CHAPTERS
    for chapter in _anchored(proposal):
        assert chapter.confidence == 0.85
        assert any(
            f"TOC entry {chapter.title!r} points to PDF page" in w for w in proposal.warnings
        )


def test_without_an_inferred_offset_nothing_is_anchored_on_the_shifted_page() -> None:
    blocks, toc = _book(headings=("Preface",))  # one named heading is not enough evidence
    proposal = _plan(blocks, toc)
    assert not any("offset" in w and "inferred" in w for w in proposal.warnings)
    assert _anchored(proposal) == []


def test_a_shifted_page_that_does_not_open_with_the_numeral_is_not_anchored() -> None:
    blocks, toc = _book(numerals=False)
    assert _anchored(_plan(blocks, toc)) == []
