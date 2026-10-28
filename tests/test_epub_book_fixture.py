"""The synthetic novel EPUB must keep the structure that made real books fail."""

from pathlib import Path

import pymupdf
import pytest
from epub_book import write_novel_epub


def _open(tmp_path: Path, **options) -> pymupdf.Document:
    return pymupdf.open(write_novel_epub(tmp_path / "novel.epub", **options))


def test_outline_points_at_pages_that_open_with_a_bare_numeral(tmp_path: Path) -> None:
    document = _open(tmp_path, chapters=6)
    outline = document.get_toc()
    assert [entry[1] for entry in outline] == [f"Chapter {n}" for n in range(1, 7)]
    for number, (_depth, _title, page) in enumerate(outline, start=1):
        first_line = document.load_page(page - 1).get_text().strip().splitlines()[0]
        assert first_line == str(number)


def test_chapter_labels_appear_only_in_the_contents_pages(tmp_path: Path) -> None:
    document = _open(tmp_path, chapters=6)
    listed = [
        index
        for index in range(len(document))
        if "Chapter 1" in document.load_page(index).get_text()
    ]
    assert listed == [3]  # contents only: the body never prints the word "Chapter"
    assert "Chapter 5" in document.load_page(4).get_text()


def test_cover_is_an_image_on_a_full_page_white_background(tmp_path: Path) -> None:
    page = _open(tmp_path).load_page(0)
    assert page.get_text().strip() == ""
    drawings = page.get_drawings()
    assert len(drawings) == 1
    assert tuple(drawings[0]["rect"]) == tuple(page.rect)
    assert drawings[0]["fill"] == (1.0, 1.0, 1.0)
    assert any(block["type"] == 1 for block in page.get_text("dict")["blocks"])


def test_options_remove_the_cover_outline_and_contents(tmp_path: Path) -> None:
    document = _open(tmp_path, outline=False, cover=False, contents=False)
    assert document.get_toc() == []
    assert document.is_reflowable
    assert "Contents" not in "".join(
        document.load_page(index).get_text() for index in range(len(document))
    )


def test_prose_headings_repeat_the_outline_title(tmp_path: Path) -> None:
    document = _open(tmp_path, body_numerals=False)
    page = document.get_toc()[0][2]
    assert document.load_page(page - 1).get_text().strip().splitlines()[0] == "Chapter 1"


def test_chapters_vary_in_length_so_numerals_are_not_page_numbers(tmp_path: Path) -> None:
    outline = _open(tmp_path, chapters=30).get_toc()
    offsets = {page - number for number, (_depth, _title, page) in enumerate(outline, start=1)}
    assert len(offsets) > 1


def test_nav_and_ncx_outlines_expose_the_same_titles_and_pages(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    ncx = pymupdf.open(write_novel_epub(tmp_path / "a" / "n.epub", chapters=8, outline="ncx"))
    nav = pymupdf.open(write_novel_epub(tmp_path / "b" / "n.epub", chapters=8, outline="nav"))
    assert nav.get_toc() == ncx.get_toc() != []
    assert [entry[1] for entry in nav.get_toc()] == [f"Chapter {n}" for n in range(1, 9)]


def test_outline_accepts_booleans_and_rejects_unknown_kinds(tmp_path: Path) -> None:
    assert _open(tmp_path, outline=True).get_toc() != []
    assert _open(tmp_path, outline=False).get_toc() == []
    with pytest.raises(ValueError, match="outline must be"):
        write_novel_epub(tmp_path / "bad.epub", outline="toc")
