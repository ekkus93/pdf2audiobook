"""Chapter-detection fixtures for bookmarks, TOC offsets, prose headings and mid-page starts."""

import pytest

from pdf2audiobook.config import Chapters
from pdf2audiobook.document.structure import propose_chapters, validate_chapter_coverage
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.models import DocumentBlock


def sample(items):
    return [
        DocumentBlock(
            id=f"b{i}", page_index=page, order=i, text=text, font_size=size,
        )
        for i, (page, text, size) in enumerate(items)
    ]


def test_unique_bookmark_with_printed_page_offset_corrects_only_nearby_anchor():
    blocks = sample([
        (0, "Front matter notice.", 11),
        (1, "The Arrival", 20),
        (1, "Body content from the beginning.", 11),
        (2, "Chapter 2", 18),
        (2, "More second chapter prose.", 11),
    ])
    chapters, warnings = propose_chapters(
        blocks, set(), [[1, "The Arrival", 1], [1, "Chapter 2", 3]], Chapters()
    )
    assert [c.start_block for c in chapters] == [0, 1, 3]
    assert chapters[1].title == "The Arrival"
    assert chapters[1].confidence < chapters[2].confidence
    assert any("matched unique title" in warning for warning in warnings)
    validate_chapter_coverage(blocks, chapters)


def test_no_toc_prose_heading_uses_strong_typographic_evidence():
    blocks = sample([
        (0, "The Arrival", 21),
        (0, "An ordinary first narrative sentence.", 11),
        (0, "Another first chapter sentence.", 11),
        (0, "The Return", 20),
        (0, "Second chapter narrative sentence.", 11),
        (0, "A second chapter continuation.", 11),
    ])
    chapters, _ = propose_chapters(blocks, set(), [], Chapters())
    assert [chapter.title for chapter in chapters] == ["The Arrival", "The Return"]
    assert all("typographic" in str(chapter.evidence) for chapter in chapters)
    validate_chapter_coverage(blocks, chapters)


def test_midpage_heading_keeps_prior_page_prose_once():
    blocks = sample([
        (0, "Chapter 1", 18), (0, "First chapter body.", 11),
        (0, "Chapter 2", 18), (0, "Second chapter body.", 11),
        (1, "Second chapter continues.", 11),
    ])
    chapters, _ = propose_chapters(blocks, set(), [], Chapters())
    assert [(c.start_block, c.end_block) for c in chapters] == [(0, 2), (2, 5)]
    validate_chapter_coverage(blocks, chapters)


def test_ambiguous_duplicate_toc_title_not_used_as_offset_anchor():
    blocks = sample([
        (0, "Introductory words.", 11),
        (1, "The Arrival", 11), (1, "Same label in prose.", 11),
        (2, "The Arrival", 11), (2, "Duplicate marker.", 11),
    ])
    with pytest.raises(ExtractionError, match="No reliable chapter boundaries"):
        propose_chapters(blocks, set(), [[1, "The Arrival", 1]], Chapters())


def test_no_toc_without_heading_requires_explicit_single_chapter():
    blocks = sample([(0, "A normal passage.", 11), (0, "Another passage.", 11)])
    with pytest.raises(ExtractionError, match="No reliable chapter boundaries"):
        propose_chapters(blocks, set(), [], Chapters())
    chapters, _ = propose_chapters(
        blocks, set(), [], Chapters(allow_single_chapter=True)
    )
    assert len(chapters) == 1
    validate_chapter_coverage(blocks, chapters)
