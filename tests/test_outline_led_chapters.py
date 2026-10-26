"""Real-book regressions: outline titles vs printed headings, and catalogue pages."""

from pdf2audiobook.config import Chapters
from pdf2audiobook.document.structure import propose_chapters, validate_chapter_coverage
from pdf2audiobook.models import DocumentBlock


def block(index: int, page: int, text: str, size: float = 11.0) -> DocumentBlock:
    return DocumentBlock(
        id=f"b{index}",
        page_index=page,
        text=text,
        span_ids=[],
        order=index,
        kind="unknown",
        font_size=size,
    )


def body(start: int, page: int, count: int = 4) -> list[DocumentBlock]:
    return [block(start + n, page, f"Ordinary body prose line {start + n}.") for n in range(count)]


def test_outline_title_matches_heading_despite_case_and_trailing_period():
    blocks = [
        block(0, 0, "CHAPTER I.", 17),
        *body(1, 0),
        block(5, 1, "CHAPTER II.", 17),
        *body(6, 1),
    ]
    toc = [[2, "Chapter I", 1], [2, "Chapter II", 2]]
    chapters, _ = propose_chapters(blocks, set(), toc, Chapters())
    validate_chapter_coverage(blocks, chapters)
    assert [c.title for c in chapters] == ["Chapter I", "Chapter II"]
    assert all(c.confidence == 0.95 for c in chapters)
    assert all("PDF bookmark" in c.evidence[0] for c in chapters)


def test_outline_led_book_ignores_large_font_catalogue_entries():
    blocks = [
        block(0, 0, "The Opening", 18),
        *body(1, 0),
        block(5, 1, "The Ending", 18),
        *body(6, 1),
        block(10, 2, "A Treatise on Things", 17),
        block(11, 2, "By A. Author. 3s. 6d.", 11),
        block(12, 2, "Another Fine Volume", 17),
        block(13, 2, "By B. Writer. 5s.", 11),
        *body(14, 2),
    ]
    toc = [[1, "The Opening", 1], [1, "The Ending", 2]]
    chapters, warnings = propose_chapters(blocks, set(), toc, Chapters())
    validate_chapter_coverage(blocks, chapters)
    assert [c.title for c in chapters] == ["The Opening", "The Ending"]
    assert chapters[-1].end_block == len(blocks)
    assert any("Ignored 2 font-size-only heading" in w for w in warnings)


def test_without_outline_typography_still_finds_headings():
    blocks = [
        block(0, 0, "The Opening", 18),
        *body(1, 0),
        block(5, 1, "The Ending", 18),
        *body(6, 1),
    ]
    chapters, _ = propose_chapters(blocks, set(), [], Chapters())
    assert [c.title for c in chapters] == ["The Opening", "The Ending"]
    assert all(c.confidence == 0.82 for c in chapters)
    assert all(
        c.warnings == ["Chapter boundary has low confidence; verify manually"] for c in chapters
    )
    assert all(c.generated_fingerprint for c in chapters)


def test_only_low_confidence_chapter_gets_boundary_warning():
    blocks = [
        block(0, 0, "Chapter 1"),
        *body(1, 0),
        block(5, 1, "A Quiet Interlude", 18),
        *body(6, 1),
    ]
    chapters, _ = propose_chapters(blocks, set(), [], Chapters())
    assert [chapter.confidence for chapter in chapters] == [0.9, 0.82]
    assert chapters[0].warnings == []
    assert chapters[1].warnings == ["Chapter boundary has low confidence; verify manually"]


def test_wrapped_large_font_lines_are_not_typographic_headings():
    blocks = [
        block(0, 0, "Chapter 1"),
        *body(1, 0),
        block(5, 1, "An Introduction to the Calculus. Based on Graphical Meth-", 17),
        block(6, 1, "of Development. Vol. I. Part I. General Determinants, up", 17),
        *body(7, 1),
    ]
    chapters, _ = propose_chapters(blocks, set(), [], Chapters())
    assert [c.title for c in chapters] == ["Chapter 1"]


def test_llm_only_headings_ignored_when_outline_matches():
    blocks = [
        block(0, 0, "The Opening", 18),
        *body(1, 0),
        block(5, 0, "***"),
        *body(6, 0),
        block(10, 1, "The Ending", 18),
        *body(11, 1),
    ]
    toc = [[1, "The Opening", 1], [1, "The Ending", 2]]
    chapters, warnings = propose_chapters(blocks, set(), toc, Chapters(), extra_heading_ids={"b5"})
    assert [c.title for c in chapters] == ["The Opening", "The Ending"]
    assert any("Ignored 1 LLM-proposed heading" in w for w in warnings)


def test_llm_only_heading_is_labelled_advisory_without_outline():
    blocks = [
        block(0, 0, "Chapter 1"),
        *body(1, 0),
        block(5, 1, "The Quiet Interlude"),
        *body(6, 1),
    ]
    chapters, _ = propose_chapters(blocks, set(), [], Chapters(), extra_heading_ids={"b5"})
    assert [c.title for c in chapters] == ["Chapter 1", "The Quiet Interlude"]
    assert chapters[1].confidence == 0.8
    assert chapters[1].evidence == ["LLM structure classification (advisory)", "opens a new page"]
