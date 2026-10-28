"""Outline matching must not rescan the book for every entry (F2)."""

from pdf2audiobook.config import Settings
from pdf2audiobook.document.structure import propose_chapters
from pdf2audiobook.models import DocumentBlock

PROSE = "Ordinary narrative prose that continues for a while on this page of the book."


class CountingBlocks(list):
    """A block list that counts how many times it is iterated from start to end."""

    passes = 0

    def __iter__(self):
        type(self).passes += 1
        return super().__iter__()


def _book(entries: int):
    blocks, toc = CountingBlocks(), []
    for number in range(1, entries + 1):
        page = number - 1
        blocks.append(DocumentBlock(id=f"n{number}", page_index=page, text=str(number)))
        blocks.append(DocumentBlock(id=f"p{number}", page_index=page, text=PROSE))
        toc.append([1, f"Chapter {number}", number])
    return blocks, toc


def _passes(entries: int) -> int:
    blocks, toc = _book(entries)
    CountingBlocks.passes = 0
    settings = Settings().chapters.model_copy(update={"allow_single_chapter": True})
    propose_chapters(blocks, set(), toc, settings)
    return CountingBlocks.passes


def test_passes_over_the_blocks_do_not_grow_with_the_number_of_outline_entries() -> None:
    small, large = _passes(40), _passes(200)
    assert large - small <= 2, (small, large)
    assert large <= 40


def test_the_anchors_are_unchanged_by_the_index() -> None:
    blocks, toc = _book(60)
    settings = Settings().chapters.model_copy(update={"allow_single_chapter": True})
    chapters = propose_chapters(blocks, set(), toc, settings).chapters
    assert [c.title for c in chapters] == [f"Chapter {n}" for n in range(1, 61)]
    assert [blocks[c.start_block].text for c in chapters] == [str(n) for n in range(1, 61)]
