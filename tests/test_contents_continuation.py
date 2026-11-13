"""A contents list continued on the next page names chapters; it never opens them."""

from pathlib import Path

from epub_book import write_novel_epub

from pdf2audiobook.config import Settings
from pdf2audiobook.document.structure import _continued_contents_page
from pdf2audiobook.models import DocumentBlock
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.workspace import read_manifest


def _blocks(pages: list[list[str]]) -> list[DocumentBlock]:
    texts = [(page, text) for page, lines in enumerate(pages) for text in lines]
    return [
        DocumentBlock(id=f"b{i}", text=text, page_index=page, order=i)
        for i, (page, text) in enumerate(texts)
    ]


CONTENTS = ["Contents", "Chapter 1", "Chapter 2", "Chapter 3"]


def test_a_page_of_the_next_labels_continues_the_contents():
    blocks = _blocks([CONTENTS, ["Chapter 4", "Chapter 5", "Chapter 6"], ["1", "Prose."]])

    assert _continued_contents_page(blocks, set(), {0, 1, 2, 3}) == {4, 5, 6}


def test_a_page_with_anything_but_the_next_labels_is_not_contents():
    for following in (
        ["Chapter 4", "It was a dark night and the rain fell."],  # opens chapter 4
        ["Chapter 5", "Chapter 6"],  # skips a number
        ["Part 4", "Part 5"],  # a different kind of label
        ["Chapter 4", "Chapter 4"],  # repeats a number
    ):
        blocks = _blocks([CONTENTS, following])
        assert _continued_contents_page(blocks, set(), {0, 1, 2, 3}) == set(), following


def test_no_contents_or_no_listed_labels_means_no_continuation():
    blocks = _blocks([["Contents", "Preface", "Notes"], ["Chapter 1", "Chapter 2"]])

    assert _continued_contents_page(blocks, set(), set()) == set()
    assert _continued_contents_page(blocks, set(), {0, 1, 2}) == set()


def test_an_epub_contents_split_over_two_pages_opens_no_chapters(tmp_path: Path):
    source = write_novel_epub(tmp_path / "novel.epub", chapters=6)
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.llm.enabled = False

    manifest = read_manifest(analyze_book(source, settings))

    assert [chapter.title for chapter in manifest.chapters] == ["Front Matter"] + [
        f"Chapter {number}" for number in range(1, 7)
    ]
