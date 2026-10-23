"""Printed contents pages as chapter evidence (real-book regressions, synthetic data)."""

from pdf2audiobook.config import Chapters
from pdf2audiobook.document.structure import propose_chapters, validate_chapter_coverage
from pdf2audiobook.models import DocumentBlock


class Book:
    def __init__(self) -> None:
        self.blocks: list[DocumentBlock] = []

    def line(self, page: int, text: str, size: float = 12.0) -> "Book":
        index = len(self.blocks)
        self.blocks.append(
            DocumentBlock(
                id=f"b{index}",
                page_index=page,
                text=text,
                span_ids=[],
                order=index,
                kind="unknown",
                font_size=size,
            )
        )
        return self

    def prose(self, page: int, count: int = 3) -> "Book":
        for n in range(count):
            self.line(page, f"Ordinary narrative sentence number {len(self.blocks)} goes on.")
        return self

    def chapters(self):
        chapters, warnings = propose_chapters(self.blocks, set(), [], Chapters())
        validate_chapter_coverage(self.blocks, chapters)
        return chapters, warnings


def test_contents_entries_find_body_size_story_headings():
    book = (
        Book()
        .line(0, "CONTENTS", 16)
        .line(0, "THE GOBLIN-SPIDER", 14)
        .line(0, "THE BOY WHO DREW CATS . . . 11", 14)
        .line(1, "THE GOBLIN-SPIDER", 14)
        .prose(1)
        .line(2, "THE BOY WHO DREW CATS", 14)
        .prose(2)
    )
    chapters, _ = book.chapters()
    assert [c.title for c in chapters] == [
        "Front Matter",
        "THE GOBLIN-SPIDER",
        "THE BOY WHO DREW CATS",
    ]
    assert chapters[1].confidence == 0.9
    assert chapters[1].evidence == ["printed contents entry matched unique later heading"]


def test_titles_wrapped_differently_in_contents_and_body():
    book = (
        Book()
        .line(0, "CONTENTS", 16)
        .line(0, "THE OLD WOMAN WHO", 14)
        .line(0, "LOST HER DUMPLINGS", 14)
        .line(0, "URASHIMA", 14)
        .line(1, "THE OLD WOMAN WHO LOST HER", 14)
        .line(1, "DUMPLINGS", 14)
        .prose(1)
        .line(2, "URASHIMA", 14)
        .prose(2)
    )
    chapters, _ = book.chapters()
    assert [c.title for c in chapters][1:] == [
        "THE OLD WOMAN WHO LOST HER DUMPLINGS",
        "URASHIMA",
    ]


def test_first_chapter_heading_after_contents_page_is_not_swallowed():
    book = (
        Book()
        .line(0, "CONTENTS", 16)
        .line(0, "The Opening", 12)
        .line(0, "The Ending", 12)
        .line(1, "The Opening", 12)
        .prose(1)
        .line(2, "The Ending", 12)
        .prose(2)
    )
    chapters, _ = book.chapters()
    assert [c.title for c in chapters] == ["Front Matter", "The Opening", "The Ending"]
    assert chapters[1].start_block == 3


def test_last_entry_on_continuation_page_before_editor_note():
    book = (
        Book()
        .line(0, "CONTENTS", 16)
        .line(0, "CHIN-CHIN KOBAKAMA", 14)
        .line(0, "URASHIMA", 14)
        .line(1, "MOMOTARO", 14)
        .line(1, "The versions of the first four tales are by Lafcadio Hearn.", 14)
        .line(2, "CHIN-CHIN KOBAKAMA", 14)
        .prose(2)
        .line(3, "URASHIMA", 14)
        .prose(3)
        .line(4, "MOMOTARO", 14)
        .prose(4)
    )
    chapters, _ = book.chapters()
    assert [c.title for c in chapters][-3:] == ["CHIN-CHIN KOBAKAMA", "URASHIMA", "MOMOTARO"]
    # The continuation-page entry is part of front matter, not its own chapter.
    assert chapters[0].title == "Front Matter" and chapters[0].end_block == 5


def test_ocr_noise_fallback_does_not_override_unique_exact_match():
    book = (
        Book()
        .line(0, "CONTENTS", 16)
        .line(0, "THE SILLY JELLY-FISH", 14)
        .line(0, "CHIN-CHIN KOBAKAMA", 14)
        .line(1, "‘THE SILLYJELLY-FISH", 14)
        .prose(1)
        .line(2, "CHIN-CHIN KOBAKAMA", 14)
        .line(2, "“Chin-chin Kobakama,", 12)
        .prose(2)
    )
    chapters, _ = book.chapters()
    assert [c.start_block for c in chapters][1:] == [3, 7]


def test_small_running_head_on_contents_page_is_not_an_entry():
    book = (
        Book()
        .line(0, "CONTENTS", 16)
        .line(0, "First Tale", 12)
        .line(0, "Second Tale", 12)
        .line(1, "A TINY RUNNING HEAD", 9)
        .line(2, "First Tale", 12)
        .prose(2)
        .line(3, "Second Tale", 12)
        .prose(3)
        .line(4, "A Tiny Running Head", 12)
        .prose(4)
    )
    chapters, _ = book.chapters()
    assert [c.title for c in chapters] == ["Front Matter", "First Tale", "Second Tale"]


def test_contents_entry_matching_chapter_subtitle_is_not_a_boundary():
    book = (
        Book()
        .line(0, "CONTENTS.", 17)
        .line(0, "I.", 12)
        .line(0, "On Relative Growings . . . . 9", 12)
        .line(0, "II.", 12)
        .line(0, "Simplest Cases . . . . 17", 12)
        .line(1, "CHAPTER I.", 17)
        .line(1, "ON RELATIVE GROWINGS.", 14)
        .prose(1)
        .line(2, "CHAPTER II.", 17)
        .line(2, "SIMPLEST CASES.", 14)
        .prose(2)
    )
    chapters, _ = book.chapters()
    assert [c.title for c in chapters] == ["Front Matter", "CHAPTER I.", "CHAPTER II."]


def test_single_matching_entry_is_not_trusted():
    book = (
        Book()
        .line(0, "CONTENTS", 16)
        .line(0, "Only One Tale", 12)
        .line(1, "Only One Tale", 12)
        .prose(1)
    )
    chapters, _ = propose_chapters(book.blocks, set(), [], Chapters(allow_single_chapter=True))
    assert [c.title for c in chapters] == ["Full Book"]
