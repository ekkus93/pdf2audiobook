"""An outline entry anchors to the chapter opening on its own page (E1)."""

from pathlib import Path

import pytest
from epub_book import write_novel_epub

from pdf2audiobook.config import Settings
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.workspace import read_manifest

CHAPTERS = 30


def _analyze(tmp_path: Path, **options):
    source = write_novel_epub(tmp_path / "novel.epub", chapters=CHAPTERS, **options)
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.llm.enabled = False
    settings.chapters.allow_single_chapter = True
    return read_manifest(analyze_book(source, settings))


def _anchored(manifest):
    """Chapters opened by an outline entry that matched the numeral on its own page."""
    return [c for c in manifest.chapters if "numbered chapter heading" in c.evidence[0]]


def test_every_outline_entry_opens_at_its_numeral_not_at_the_contents(tmp_path: Path) -> None:
    manifest = _analyze(tmp_path)
    chapters = _anchored(manifest)
    assert [c.title for c in chapters] == [f"Chapter {n}" for n in range(1, CHAPTERS + 1)]
    for number, chapter in enumerate(chapters, start=1):
        assert manifest.blocks[chapter.start_block].text.strip() == str(number)
        assert chapter.end_block - chapter.start_block >= 3


def test_anchored_chapters_are_high_confidence_and_cite_the_outline(tmp_path: Path) -> None:
    manifest = _analyze(tmp_path)
    for chapter in _anchored(manifest):
        assert chapter.confidence == 0.95
        assert chapter.evidence[0].startswith("PDF bookmark")
    assert not any("matched unique title on page" in w for w in manifest.warnings)


@pytest.mark.parametrize("cover", [True, False])
def test_the_result_does_not_depend_on_having_a_cover(tmp_path: Path, cover: bool) -> None:
    assert len(_anchored(_analyze(tmp_path, cover=cover))) == CHAPTERS


def test_a_chapter_is_not_anchored_to_a_numeral_that_names_another_chapter(
    tmp_path: Path,
) -> None:
    from pdf2audiobook.document.structure import bare_number, label_number

    assert label_number("Chapter 2") == 2 and bare_number("3") == 3
    manifest = _analyze(tmp_path)
    for chapter in _anchored(manifest):
        assert bare_number(manifest.blocks[chapter.start_block].text) == label_number(chapter.title)


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Chapter 12", 12),
        ("CHAPTER XII", 12),
        ("Chapter Twelve", 12),
        ("Chapter twenty-one", 21),
        ("Part 3", 3),
        ("Chapter 7: The Sea", 7),
        ("CHAPTEE IV.", 4),
        ("Chapter", None),
        ("Chapters 4", None),
        ("Chapter IIII", None),
        ("Preface", None),
        ("The 12 Chapters", None),
    ],
)
def test_label_number_reads_the_chapter_forms_books_use(text: str, value: int | None) -> None:
    from pdf2audiobook.document.structure import label_number

    assert label_number(text) == value


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("12", 12),
        ("12.", 12),
        ("XII", 12),
        ("I", 1),
        ("xii", None),
        ("1234", None),
        ("Twelve", None),
    ],
)
def test_bare_number_accepts_only_a_lone_numeral(text: str, value: int | None) -> None:
    from pdf2audiobook.document.structure import bare_number

    assert bare_number(text) == value
