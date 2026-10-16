"""Mixed bookmark and visible-heading chapter discovery."""
from pdf2audiobook.config import Chapters
from pdf2audiobook.document.structure import propose_chapters
from pdf2audiobook.models import DocumentBlock


def test_bookmarks_extend_regular_expression_headings():
    blocks = [
        DocumentBlock(id="c1", text="Chapter 1", page_index=0),
        DocumentBlock(id="p1", text="Once upon a time.", page_index=0),
        DocumentBlock(id="c2", text="The Strange Discovery", page_index=1),
        DocumentBlock(id="p2", text="Another passage.", page_index=1),
        DocumentBlock(id="c3", text="Chapter 3", page_index=2),
        DocumentBlock(id="p3", text="The final passage.", page_index=2),
    ]
    chapters, warnings = propose_chapters(
        blocks, set(),
        [[1, "Chapter 1", 1], [1, "The Strange Discovery", 2], [1, "Chapter 3", 3]],
        Chapters(),
    )
    assert [c.start_block for c in chapters] == [0, 2, 4]
    assert [c.end_block for c in chapters] == [2, 4, 6]
    assert [c.title for c in chapters] == [
        "Chapter 1", "The Strange Discovery", "Chapter 3",
    ]
    assert chapters[1].confidence == 0.95
    assert "bookmark" in chapters[1].evidence[0].lower()
    assert warnings == []


def test_bookmark_mismatch_does_not_invent_chapter():
    blocks = [
        DocumentBlock(id="c1", text="Chapter 1", page_index=0),
        DocumentBlock(id="p1", text="Ordinary prose about The Strange Discovery", page_index=1),
    ]
    chapters, _ = propose_chapters(
        blocks, set(), [[1, "The Strange Discovery", 2]], Chapters()
    )
    assert len(chapters) == 1
    assert chapters[0].title == "Chapter 1"
