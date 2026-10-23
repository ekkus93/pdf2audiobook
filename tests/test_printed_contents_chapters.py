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
    assert chapters[1].evidence == [
        "printed contents entry matched unique later heading",
        "opens a new page",
    ]


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


def test_scan_noise_in_large_type_is_not_a_heading():
    book = Book().line(0, "Opening Notice", 18).prose(0)
    for noise in ("'", "I", "1 8", "' ., . • • •", "000 I", "=============="):
        book.line(1, noise, 18).prose(1)
    book.line(2, "Closing Notice", 18).prose(2)
    chapters, _ = book.chapters()
    assert [c.title for c in chapters] == ["Opening Notice", "Closing Notice"]


def test_lone_roman_one_is_a_heading_beside_later_numerals():
    book = Book().line(0, "I", 18).prose(0).line(1, "II", 18).prose(1).line(2, "III", 18).prose(2)
    chapters, _ = book.chapters()
    assert [c.title for c in chapters] == ["I", "II", "III"]


def test_sentence_citing_a_chapter_is_not_a_chapter_label():
    book = (
        Book()
        .line(0, "CHAPTER I THE NATURE OF VERSE", 14)
        .prose(0)
        .line(1, "CHAPTER II RHYME", 14)
        .prose(1)
        .line(2, "Chapter IV regarding the change in Shakespeare's blank", 12)
        .prose(2)
    )
    chapters, _ = book.chapters()
    assert [c.title for c in chapters] == ["CHAPTER I THE NATURE OF VERSE", "CHAPTER II RHYME"]


def test_mixed_script_ocr_mojibake_is_not_a_heading():
    book = Book().line(0, "Opening Notice", 18).prose(0)
    book.line(1, "BŎrngD--;;ԎԍԌ", 18).prose(1).line(1, "1IѴѵѶ:ѷ Ѹѹre¥", 18).prose(1)
    book.line(2, "Closing Notice", 18).prose(2).line(2, "Последняя глава", 18).prose(2)
    chapters, _ = book.chapters()
    assert [c.title for c in chapters] == ["Opening Notice", "Closing Notice", "Последняя глава"]


def _scan_history_book() -> Book:
    """Contents pages listing chapter labels, then the chapters (Gibbon-like scan)."""
    book = Book()
    for page, labels in ((0, ("CHAPTER I", "CHAPTER II")), (1, ("CHAPTER III",))):
        for label in labels:
            book.line(page, label, 12)
            for n in range(5):
                book.line(page, f"Topic {n} of the listed chapter    {10 * n + 3}", 12)
    for page, label in enumerate(("CHAPTEE I", "CHAPTER II", "CHAPTER III"), start=2):
        book.line(page, label, 12).prose(page)
        # A display-size marginal note mid-chapter is not a chapter opening.
        book.line(page, "Dacia and Arabia", 18).prose(page)
    return book


def test_contents_listing_labels_yield_to_later_chapter_labels():
    chapters, warnings = _scan_history_book().chapters()
    assert [c.title for c in chapters] == ["Front Matter", "CHAPTEE I", "CHAPTER II", "CHAPTER III"]
    assert [c.confidence for c in chapters[1:]] == [0.9, 0.9, 0.9]
    assert any("numbered chapter labels" in warning for warning in warnings)


def test_large_type_crowding_a_page_is_not_a_run_of_chapters():
    book = Book().line(0, "Opening Notice", 18).prose(0)
    for word in ("Harvesters", "Surgical", "Valuable Books", "Selections", "Fits"):
        book.line(1, word, 18).line(1, "small print advertisement copy", 12)
    book.line(2, "Closing Notice", 18).prose(2)
    chapters, _ = book.chapters()
    assert [c.title for c in chapters] == ["Opening Notice", "Closing Notice"]


def test_large_type_contents_line_with_page_reference_is_not_a_heading():
    book = Book().line(0, "Opening Notice", 18).prose(0)
    book.line(1, "Conquests of Trajan in the East    6", 18).prose(1)
    book.line(2, "Closing Notice", 18).prose(2)
    chapters, _ = book.chapters()
    assert [c.title for c in chapters] == ["Opening Notice", "Closing Notice"]


def test_bookmarked_label_on_number_heavy_page_is_kept():
    book = Book().line(0, "Chapter X", 12).prose(0)
    book.line(1, "Chapter XI", 12)
    for n in range(8):
        book.line(1, f"y equals x squared plus {n}", 12)
    book.line(2, "Chapter XI", 12).prose(2)  # later mention, e.g. an exercise heading
    toc = [[1, "Chapter X", 1], [1, "Chapter XI", 2]]
    chapters, _ = propose_chapters(book.blocks, set(), toc, Chapters())
    assert [(c.title, c.start_block) for c in chapters][:2] == [("Chapter X", 0), ("Chapter XI", 4)]


def _placed(index, page, text, top, size=12.0):
    return DocumentBlock(
        id=f"w{index}",
        page_index=page,
        text=text,
        span_ids=[],
        order=index,
        kind="unknown",
        font_size=size,
        bbox=(72, top, 400, top + size),
    )


def test_whitespace_separates_display_headings_from_packed_display_lines():
    blocks = [_placed(0, 0, "Opening Section", 72, 18)]
    blocks += [
        _placed(n, 0, f"Ordinary body sentence {n} runs on.", 72 + 14 * n) for n in range(1, 6)
    ]
    # Packed against the body line above: a drop-cap or advert line.
    blocks.append(_placed(6, 0, "Packed Display Words", 72 + 14 * 6 - 1, 18))
    blocks += [
        _placed(n, 0, f"More body sentence {n} runs on.", 72 + 14 * n + 8) for n in range(7, 10)
    ]
    # Separated by a gap: a real section opening mid-page.
    blocks.append(_placed(10, 0, "Second Section", 72 + 14 * 10 + 30, 18))
    blocks += [
        _placed(n, 0, f"Final body sentence {n} runs on.", 72 + 14 * n + 50) for n in range(11, 14)
    ]
    chapters, _ = propose_chapters(blocks, set(), [], Chapters())
    assert [c.title for c in chapters] == ["Opening Section", "Second Section"]
    assert chapters[0].evidence[-1] == "opens a new page"
    assert chapters[1].evidence[-1] == "vertical whitespace above"
