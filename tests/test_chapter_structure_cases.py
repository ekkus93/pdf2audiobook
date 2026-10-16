"""Chapter segmentation regression: front matter, parts, prologue and mid-page starts."""
from pdf2audiobook.config import Chapters
from pdf2audiobook.document.structure import (
    chapter_text,
    propose_chapters,
    validate_chapter_coverage,
)
from pdf2audiobook.models import DocumentBlock


def block(index: int, page: int, text: str) -> DocumentBlock:
    return DocumentBlock(
        id=f"b{index}", page_index=page, text=text,
        span_ids=[], order=index, kind="unknown",
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
        "Front Matter", "Prologue", "Part I", "Chapter 1",
        "Chapter 2", "Part II", "Chapter 3", "Epilogue",
    ]
    assert [c.start_block for c in chapters] == [0, 1, 3, 4, 6, 8, 9, 11]
    assert [c.end_block for c in chapters] == [1, 3, 4, 6, 8, 9, 11, 13]
    assert any("Pre-chapter material retained" in warning for warning in warnings)
    assert sum(c.end_block - c.start_block for c in chapters) == len(blocks)
    texts = [chapter_text(blocks, chapter, set()) for chapter in chapters]
    assert "first chapter" in texts[3]
    assert "Another chapter" in texts[4]
    assert all(text.endswith("\n") for text in texts)
    assert "The opening story" not in texts[3]


def test_bookmark_boundary_mid_page_and_exact_coverage():
    blocks = [
        block(0, 0, "Chapter 1"),
        block(1, 0, "Chapter one prose before a second heading."),
        block(2, 0, "A New Beginning"),
        block(3, 0, "New chapter prose after a mid-page heading."),
    ]
    toc = [[1, "A New Beginning", 1]]
    chapters, _ = propose_chapters(blocks, set(), toc, Chapters())
    validate_chapter_coverage(blocks, chapters)
    assert [c.start_block for c in chapters] == [0, 2]
    assert chapters[1].title == "A New Beginning"
    assert "PDF bookmark" in chapters[1].evidence[0]
    assert "New chapter prose" not in chapter_text(blocks, chapters[0], set())
