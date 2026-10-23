"""Printed TOC offsets require multiple independent unique heading anchors."""

from pdf2audiobook.config import Chapters
from pdf2audiobook.document.structure import propose_chapters, validate_chapter_coverage
from pdf2audiobook.models import DocumentBlock


def offset_book():
    return [
        DocumentBlock(id="h1", page_index=5, text="Chapter 1", kind="heading"),
        DocumentBlock(id="p1", page_index=5, text="First prose.", kind="paragraph"),
        DocumentBlock(id="h2", page_index=6, text="Chapter 2", kind="heading"),
        DocumentBlock(id="p2", page_index=6, text="Second prose.", kind="paragraph"),
        DocumentBlock(id="h3", page_index=7, text="The Quiet Forest", kind="paragraph"),
        DocumentBlock(id="p3", page_index=7, text="Third prose.", kind="paragraph"),
    ]


def test_consistent_printed_page_offset_recovers_unmarked_chapter():
    blocks = offset_book()
    chapters, warnings = propose_chapters(
        blocks,
        set(),
        [[1, "Chapter 1", 1], [1, "Chapter 2", 2], [1, "The Quiet Forest", 3]],
        Chapters(),
    )
    validate_chapter_coverage(blocks, chapters)
    assert [chapter.title for chapter in chapters] == ["Chapter 1", "Chapter 2", "The Quiet Forest"]
    assert [chapter.start_block for chapter in chapters] == [0, 2, 4]
    assert [chapter.confidence for chapter in chapters] == [0.85, 0.85, 0.85]
    assert any("page offset +5 inferred from 2 unique headings" in w for w in warnings)


def test_conflicting_offsets_do_not_invent_chapter_boundary():
    blocks = offset_book()
    chapters, warnings = propose_chapters(
        blocks,
        set(),
        [[1, "Chapter 1", 1], [1, "Chapter 2", 10], [1, "The Quiet Forest", 3]],
        Chapters(),
    )
    validate_chapter_coverage(blocks, chapters)
    assert [chapter.title for chapter in chapters] == ["Chapter 1", "Chapter 2"]
    assert not any("page offset" in w for w in warnings)


def test_one_offset_anchor_is_insufficient():
    blocks = offset_book()
    chapters, warnings = propose_chapters(
        blocks, set(), [[1, "Chapter 1", 1], [1, "The Quiet Forest", 3]], Chapters()
    )
    validate_chapter_coverage(blocks, chapters)
    assert [chapter.title for chapter in chapters] == ["Chapter 1", "Chapter 2"]
    assert not any("page offset" in w for w in warnings)


def test_exact_physical_page_bookmarks_remain_high_confidence():
    blocks = offset_book()
    chapters, warnings = propose_chapters(
        blocks, set(), [[1, "Chapter 1", 6], [1, "Chapter 2", 7]], Chapters()
    )
    validate_chapter_coverage(blocks, chapters)
    assert chapters[0].confidence == chapters[1].confidence == 0.95
    assert not any("page offset" in w for w in warnings)
