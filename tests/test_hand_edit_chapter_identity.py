"""Hand edits follow their chapter, not its number, when reanalysis changes the count (R75)."""

import fitz
import pytest

import pdf2audiobook.pipeline as pipeline
from pdf2audiobook.config import LLM, General, Settings
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.models import Chapter
from pdf2audiobook.workspace import read_manifest, write_manifest


def _source(path):
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 80), "Chapter 1")
    page.insert_text((72, 120), "First chapter contains enough readable prose.")
    page.insert_text((72, 180), "Chapter 2")
    page.insert_text((72, 220), "Second chapter contains more readable prose.")
    document.save(path)
    document.close()


def _chapter(number, title, start, end):
    return Chapter(
        id=f"c{number:04d}",
        number=number,
        title=title,
        start_block=start,
        end_block=end,
        confidence=1.0,
    )


def _setup(tmp_path):
    source = tmp_path / "book.pdf"
    _source(source)
    settings = Settings(general=General(output_dir=str(tmp_path / "out")), llm=LLM(enabled=False))
    manifest_path = pipeline.analyze_book(source, settings)
    manifest = read_manifest(manifest_path)
    assert [chapter.title for chapter in manifest.chapters] == ["Chapter 1", "Chapter 2"]
    reanalysis = settings.model_copy(
        update={"general": General(output_dir=str(tmp_path / "out"), resume=False)}
    )
    return source, manifest_path, manifest, reanalysis


def test_edit_stays_with_its_chapter_when_a_chapter_is_inserted_before_it(tmp_path, monkeypatch):
    source, manifest_path, manifest, reanalysis = _setup(tmp_path)
    second_start = manifest.chapters[1].start_block
    manifest.chapters[1].title = "My edited second title"
    write_manifest(manifest_path, manifest)

    def with_inserted_chapter(blocks, *_args, **_kwargs):
        total = len(blocks)
        return [
            _chapter(1, "Inserted", 0, 1),
            _chapter(2, "Chapter 1", 1, second_start),
            _chapter(3, "Chapter 2", second_start, total),
        ], []

    monkeypatch.setattr(pipeline, "propose_chapters", with_inserted_chapter)
    refreshed = read_manifest(pipeline.analyze_book(source, reanalysis))
    assert [chapter.title for chapter in refreshed.chapters] == [
        "Inserted",
        "Chapter 1",
        "My edited second title",
    ]
    assert "Preserved user-edited chapter numbers: 3" in refreshed.warnings


def test_edit_whose_chapter_disappeared_is_a_content_free_conflict(tmp_path, monkeypatch):
    source, manifest_path, manifest, reanalysis = _setup(tmp_path)
    manifest.chapters[1].title = "My private edited title"
    write_manifest(manifest_path, manifest)

    def merged(blocks, *_args, **_kwargs):
        return [_chapter(1, "Everything", 0, len(blocks))], []

    monkeypatch.setattr(pipeline, "propose_chapters", merged)
    with pytest.raises(
        ExtractionError, match="Chapter 2 was edited but cannot be aligned"
    ) as error:
        pipeline.analyze_book(source, reanalysis)
    assert "My private edited title" not in str(error.value)
    assert "First chapter" not in str(error.value)
