"""Contents-page labels name chapters; they must not become chapters themselves (E2)."""

from pathlib import Path

import pytest
from epub_book import write_novel_epub

from pdf2audiobook.config import Settings
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.workspace import read_manifest

CHAPTERS = 12


_CACHE: dict[tuple, object] = {}


def _analyze(tmp_path: Path, **options):
    """Analyze once per distinct option set: building and analyzing a book is slow."""
    key = tuple(sorted(options.items()))
    if key not in _CACHE:
        folder = tmp_path.parent / f"shared-{abs(hash(key))}"
        folder.mkdir(exist_ok=True)
        source = write_novel_epub(folder / "novel.epub", chapters=CHAPTERS, **options)
        settings = Settings()
        settings.general.output_dir = str(folder / "out")
        settings.llm.enabled = False
        settings.chapters.allow_single_chapter = True
        _CACHE[key] = read_manifest(analyze_book(source, settings))
    return _CACHE[key]


def _numbered(manifest):
    return [c for c in manifest.chapters if c.title.startswith("Chapter ")]


def _contents_pages(manifest) -> set[int]:
    pages = {b.page_index for b in manifest.blocks if b.text.strip() == "Contents"}
    return pages | {page + 1 for page in pages}


def _assert_clean_plan(manifest) -> None:
    chapters = _numbered(manifest)
    assert [c.title for c in chapters] == [f"Chapter {n}" for n in range(1, CHAPTERS + 1)]
    for number, chapter in enumerate(chapters, start=1):
        start = manifest.blocks[chapter.start_block]
        assert start.text.strip() == str(number)
        assert start.page_index not in _contents_pages(manifest)
        assert chapter.end_block - chapter.start_block >= 3
    # Numbered chapters plus whatever front matter precedes them, nothing else.
    assert len(manifest.chapters) <= CHAPTERS + 4
    sizes = sorted(c.end_block - c.start_block for c in manifest.chapters)
    assert sizes[-1] <= 3 * sizes[len(sizes) // 2]  # no chapter swallows the book


def test_with_an_outline_no_contents_label_becomes_a_chapter(tmp_path: Path) -> None:
    _assert_clean_plan(_analyze(tmp_path))


def test_without_an_outline_numerals_named_by_the_contents_are_headings(tmp_path: Path) -> None:
    manifest = _analyze(tmp_path, outline=False)
    _assert_clean_plan(manifest)
    for chapter in _numbered(manifest):
        assert chapter.evidence[0].startswith("numeral heading corroborated")
        assert chapter.confidence == 0.9


def test_prose_headings_without_an_outline_behave_as_before(tmp_path: Path) -> None:
    manifest = _analyze(tmp_path, outline=False, body_numerals=False)
    chapters = _numbered(manifest)
    assert [c.title for c in chapters] == [f"Chapter {n}" for n in range(1, CHAPTERS + 1)]
    for chapter in chapters:
        start = manifest.blocks[chapter.start_block]
        assert start.page_index not in _contents_pages(manifest)


def test_numerals_without_a_printed_contents_are_not_trusted(tmp_path: Path) -> None:
    manifest = _analyze(tmp_path, outline=False, contents=False)
    assert not _numbered(manifest)
    assert not any(c.evidence[0].startswith("numeral heading") for c in manifest.chapters)


def test_a_stray_page_top_number_is_not_a_chapter(tmp_path: Path) -> None:
    from pdf2audiobook.document.structure import propose_chapters
    from pdf2audiobook.models import DocumentBlock

    def block(i: int, page: int, text: str) -> DocumentBlock:
        return DocumentBlock(id=f"b{i}", page_index=page, text=text, kind="paragraph")

    listing = [block(i, 0, f"Chapter {n}") for i, n in enumerate(range(1, 9))]
    # Only two body numerals appear (fewer than three): they must not be accepted.
    body = [
        block(20, 1, "1"),
        block(21, 1, "Some opening prose of the first part of the story."),
        block(22, 2, "2"),
        block(23, 2, "Some opening prose of the second part of the story."),
    ]
    proposal = propose_chapters(
        [*listing, *body],
        set(),
        [],
        Settings().chapters.model_copy(update={"allow_single_chapter": True}),
    )
    assert not any(
        c.evidence and c.evidence[0].startswith("numeral heading") for c in proposal.chapters
    )


@pytest.mark.parametrize("chapters", [12, 16])
def test_the_plan_is_stable_across_book_sizes(tmp_path: Path, chapters: int) -> None:
    source = write_novel_epub(tmp_path / "n.epub", chapters=chapters, outline=False)
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.llm.enabled = False
    manifest = read_manifest(analyze_book(source, settings))
    assert len(_numbered(manifest)) == chapters


def test_running_page_numbers_are_not_mistaken_for_chapter_numerals() -> None:
    from pdf2audiobook.document.structure import propose_chapters
    from pdf2audiobook.models import DocumentBlock

    def block(i: int, page: int, text: str) -> DocumentBlock:
        return DocumentBlock(id=f"b{i}", page_index=page, text=text, kind="paragraph")

    blocks = [block(i, 0, f"Chapter {n}") for i, n in enumerate(range(1, 9))]
    for page in range(1, 9):  # every page starts with its own number: 1, 2, 3 ...
        blocks.append(block(100 + page * 2, page, str(page)))
        blocks.append(block(101 + page * 2, page, f"Ordinary prose on page {page} of the book."))
    proposal = propose_chapters(
        blocks, set(), [], Settings().chapters.model_copy(update={"allow_single_chapter": True})
    )
    assert not any(c.evidence[0].startswith("numeral heading") for c in proposal.chapters)
