"""Malformed bookmark metadata cannot interrupt source-aligned chapter planning."""

import pytest

from pdf2audiobook.config import Chapters
from pdf2audiobook.document.structure import propose_chapters, validate_chapter_coverage
from pdf2audiobook.models import DocumentBlock


def book_blocks():
    return [
        DocumentBlock(id="b1", page_index=0, text="Chapter 1", kind="heading"),
        DocumentBlock(id="b2", page_index=0, text="First chapter prose.", kind="paragraph"),
        DocumentBlock(id="b3", page_index=1, text="Chapter 2", kind="heading"),
        DocumentBlock(id="b4", page_index=1, text="Second chapter prose.", kind="paragraph"),
    ]


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        7,
        {},
        [],
        [1, "Chapter 1"],
        ["1", "Chapter 1", 1],
        [True, "Chapter 1", 1],
        [0, "Chapter 1", 1],
        [1, "Chapter 1", "1"],
        [1, "Chapter 1", float("nan")],
        [1, "Chapter 1", True],
        [1, "Chapter 1", 0],
        [1, None, 1],
    ],
)
def test_invalid_bookmark_entries_are_skipped_without_losing_chapters(invalid):
    blocks = book_blocks()
    chapters, warnings = propose_chapters(
        blocks, set(), [invalid, [1, "Chapter 1", 1], [1, "Chapter 2", 2]], Chapters()
    )
    validate_chapter_coverage(blocks, chapters)
    assert [chapter.title for chapter in chapters] == ["Chapter 1", "Chapter 2"]
    assert all(chapter.confidence == 0.95 for chapter in chapters)
    assert any("Skipped 1 malformed PDF bookmark" in warning for warning in warnings)


def test_valid_deep_bookmark_is_ignored_without_malformed_warning():
    blocks = book_blocks()
    chapters, warnings = propose_chapters(
        blocks, set(), [[3, "A subheading", 1], [1, "Chapter 1", 1]], Chapters()
    )
    validate_chapter_coverage(blocks, chapters)
    assert len(chapters) == 2
    assert not any("malformed PDF bookmark" in warning for warning in warnings)


def test_all_malformed_bookmarks_keep_textual_heading_fallback():
    blocks = book_blocks()
    chapters, warnings = propose_chapters(
        blocks, set(), [None, ["invalid"], [1, "Chapter 1", False]], Chapters()
    )
    validate_chapter_coverage(blocks, chapters)
    assert [chapter.title for chapter in chapters] == ["Chapter 1", "Chapter 2"]
    assert all(chapter.confidence == 0.9 for chapter in chapters)
    assert any("Skipped 3 malformed PDF bookmark" in warning for warning in warnings)
