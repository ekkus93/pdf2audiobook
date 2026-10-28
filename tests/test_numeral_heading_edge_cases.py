"""Corroborated numeral headings: clean titles, no page numbers, parts kept apart (E2 follow-up)."""

import pytest

from pdf2audiobook.config import Settings
from pdf2audiobook.document.structure import contents_label_title, label_key, propose_chapters
from pdf2audiobook.models import DocumentBlock

PROSE = "Ordinary narrative prose that continues for a while on this page of the book."
WORDS = "One Two Three Four Five Six Seven Eight".split()


def _block(i: int, page: int, text: str) -> DocumentBlock:
    return DocumentBlock(id=f"b{i}", page_index=page, text=text, kind="paragraph")


def _chapters(blocks: list[DocumentBlock]):
    settings = Settings().chapters.model_copy(update={"allow_single_chapter": True})
    return propose_chapters(blocks, set(), [], settings).chapters


def _numerals(chapters):
    return [c for c in chapters if c.evidence[0].startswith("numeral heading")]


def _body(pages_per_chapter: list[int], first_page: int = 1, start_id: int = 100):
    """Chapters that open with a bare numeral and run for the given number of pages."""
    blocks, k, page = [], start_id, first_page
    for number, pages in enumerate(pages_per_chapter, start=1):
        blocks += [_block(k, page, str(number)), _block(k + 1, page, PROSE)]
        k += 2
        for extra in range(1, pages):
            blocks.append(_block(k, page + extra, PROSE))
            k += 1
        page += pages
    return blocks


def test_titles_drop_contents_leaders_and_page_numbers() -> None:
    contents = [_block(0, 0, "Contents")] + [
        _block(i, 0, f"Chapter {word} ........ {i * 7}") for i, word in enumerate(WORDS, 1)
    ]
    chapters = _numerals(_chapters(contents + _body([2, 3, 2, 3, 2, 3, 2, 3])))
    assert [c.title for c in chapters] == [f"Chapter {word}" for word in WORDS]


@pytest.mark.parametrize(
    ("text", "title"),
    [
        ("Chapter One ........ 7", "Chapter One"),
        ("Chapter IV ....... 31", "Chapter IV"),
        ("Chapter One: The Sea ..... 12", "Chapter One: The Sea"),
        ("Chapter One …… xii", "Chapter One"),
        ("Chapter IV", "Chapter IV"),  # a roman chapter number is not a page reference
        ("Chapter 7", "Chapter 7"),
    ],
)
def test_contents_label_title(text: str, title: str) -> None:
    assert contents_label_title(text) == title


def test_running_page_numbers_with_a_gap_are_not_chapters() -> None:
    blocks = [_block(i, 0, f"Chapter {i}") for i in range(1, 9)]
    k, page = 100, 1
    for number in range(1, 11):
        if page == 4:  # an unnumbered plate page shifts the page-number offset once
            blocks.append(_block(k, page, PROSE))
            k, page = k + 1, page + 1
        blocks += [_block(k, page, str(number)), _block(k + 1, page, PROSE)]
        k, page = k + 2, page + 1
    assert _numerals(_chapters(blocks)) == []


def test_a_book_with_some_one_page_chapters_is_still_recognised() -> None:
    contents = [_block(i, 0, f"Chapter {i}") for i in range(1, 9)]
    chapters = _numerals(_chapters(contents + _body([1, 3, 1, 2, 4, 1, 2, 3])))
    assert [c.title for c in chapters] == [f"Chapter {n}" for n in range(1, 9)]


def test_part_labels_do_not_title_or_cancel_chapters() -> None:
    order = ["Part 1", "Chapter 1", "Chapter 2", "Chapter 3", "Part 2"]
    order += [f"Chapter {n}" for n in range(4, 9)]
    contents = [_block(i, 0, text) for i, text in enumerate(order)]
    blocks = contents + [_block(50, 1, "Part 1"), _block(51, 1, PROSE)]
    blocks += _body([2, 3, 2], first_page=2, start_id=100)
    blocks += [_block(60, 9, "Part 2"), _block(61, 9, PROSE)]
    blocks += [
        block.model_copy(update={"text": str(int(block.text) + 3)})
        if block.text.isdigit()
        else block
        for block in _body([2, 3, 2, 3, 2], first_page=10, start_id=200)
    ]
    titles = [c.title for c in _chapters(blocks)]
    assert [t for t in titles if t.startswith("Chapter")] == [f"Chapter {n}" for n in range(1, 9)]
    assert "Part 1" in titles and "Part 2" in titles


def test_label_key_separates_parts_from_chapters() -> None:
    assert label_key("Part 3") == ("part", 3)
    assert label_key("CHAPTER III") == ("chapter", 3)
    assert label_key("Prologue") is None
