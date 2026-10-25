"""Chapter segmentation regression: front matter, parts, prologue and mid-page starts."""

from pdf2audiobook.config import Chapters
from pdf2audiobook.document.structure import (
    propose_chapters,
    validate_chapter_coverage,
)
from pdf2audiobook.models import DocumentBlock


def block(index: int, page: int, text: str) -> DocumentBlock:
    return DocumentBlock(
        id=f"b{index}",
        page_index=page,
        text=text,
        span_ids=[],
        order=index,
        kind="unknown",
    )


def proposal_text(blocks, chapter, omitted):
    """Project proposal boundaries in the same form used by chapter text files."""
    return (
        "\n".join(
            item.text
            for item in blocks[chapter.start_block : chapter.end_block]
            if item.id not in omitted
        ).strip()
        + "\n"
    )


def test_front_matter_prologue_multiple_parts_and_epilogue():
    blocks = [
        block(0, 0, "Copyright and publishing notes"),
        block(1, 1, "Prologue"),
        block(2, 1, "The opening story begins."),
        block(3, 2, "Part I"),
        block(4, 2, "Chapter 1"),
        block(5, 2, "The first chapter begins on the same page."),
        block(6, 3, "Chapter 2"),
        block(7, 3, "Another chapter starts partway through the page."),
        block(8, 4, "Part II"),
        block(9, 4, "Chapter 3"),
        block(10, 4, "The next chapter is on the same page as Part II."),
        block(11, 5, "Epilogue"),
        block(12, 5, "The story ends here."),
    ]
    chapters, warnings = propose_chapters(blocks, set(), [], Chapters())
    validate_chapter_coverage(blocks, chapters)
    assert [c.title for c in chapters] == [
        "Front Matter",
        "Prologue",
        "Part I",
        "Chapter 1",
        "Chapter 2",
        "Part II",
        "Chapter 3",
        "Epilogue",
    ]
    assert [c.start_block for c in chapters] == [0, 1, 3, 4, 6, 8, 9, 11]
    assert [c.end_block for c in chapters] == [1, 3, 4, 6, 8, 9, 11, 13]
    assert any("Pre-chapter material retained" in warning for warning in warnings)
    assert sum(c.end_block - c.start_block for c in chapters) == len(blocks)
    texts = [proposal_text(blocks, chapter, set()) for chapter in chapters]
    assert "first chapter" in texts[3]
    assert "Another chapter" in texts[4]
    assert all(text.endswith("\n") for text in texts)
    assert "The opening story" not in texts[3]


def test_bookmark_boundary_mid_page_and_exact_coverage():
    blocks = [
        block(0, 0, "Chapter 1"),
        block(1, 0, "Opening prose continues before the next heading."),
        block(2, 0, "A New Beginning"),
        block(3, 0, "New chapter prose after a mid-page heading."),
    ]
    toc = [[1, "A New Beginning", 1]]
    chapters, _ = propose_chapters(blocks, set(), toc, Chapters())
    validate_chapter_coverage(blocks, chapters)
    assert [c.start_block for c in chapters] == [0, 2]
    assert chapters[1].title == "A New Beginning"
    assert "PDF bookmark" in chapters[1].evidence[0]
    assert "New chapter prose" not in proposal_text(blocks, chapters[0], set())


def test_removed_running_header_before_first_heading_is_not_front_matter():
    blocks = [
        block(0, 0, "THE KEEPER OF THE LIGHT"),
        block(1, 0, "Chapter 1"),
        block(2, 0, "Opening prose."),
        block(3, 1, "Chapter 2"),
        block(4, 1, "More prose."),
    ]
    chapters, warnings = propose_chapters(blocks, {"b0"}, [], Chapters())
    validate_chapter_coverage(blocks, chapters)
    assert [c.title for c in chapters] == ["Chapter 1", "Chapter 2"]
    assert [(c.start_block, c.end_block) for c in chapters] == [(0, 3), (3, 5)]
    assert all(c.confidence >= 0.75 for c in chapters)
    assert not any("Pre-chapter material retained" in warning for warning in warnings)
    first = proposal_text(blocks, chapters[0], {"b0"})
    assert first.startswith("Chapter 1") and "KEEPER" not in first


def test_retained_text_before_first_heading_still_gets_front_matter():
    blocks = [
        block(0, 0, "RUNNING HEADER"),
        block(1, 0, "A dedication that must not be dropped."),
        block(2, 0, "Chapter 1"),
        block(3, 0, "Opening prose."),
    ]
    chapters, warnings = propose_chapters(blocks, {"b0"}, [], Chapters())
    validate_chapter_coverage(blocks, chapters)
    assert [c.title for c in chapters] == ["Front Matter", "Chapter 1"]
    assert any("Pre-chapter material retained" in warning for warning in warnings)
