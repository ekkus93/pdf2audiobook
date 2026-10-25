"""Hand edits follow their chapter, not its number, when reanalysis changes the count (R75)."""

import fitz
import pytest

import pdf2audiobook.pipeline as pipeline
from pdf2audiobook.config import LLM, General, Settings
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.models import Chapter, generated_chapter_fingerprint
from pdf2audiobook.workspace import read_manifest, write_manifest


def _source(path):
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 80), "Chapter 1")
    page.insert_text((72, 120), "First chapter contains enough readable prose.")
    page.insert_text((72, 150), "Another paragraph in the first chapter.")
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
    assert str(error.value).endswith("approve or revert the named chapter(s).")


def test_two_sided_boundary_edit_survives_reanalysis(tmp_path):
    source, manifest_path, manifest, reanalysis = _setup(tmp_path)
    new_boundary = manifest.chapters[1].start_block + 1
    assert new_boundary < len(manifest.blocks)
    manifest.chapters[0].end_block = new_boundary
    manifest.chapters[1].start_block = new_boundary
    write_manifest(manifest_path, manifest)

    refreshed = read_manifest(pipeline.analyze_book(source, reanalysis))
    assert refreshed.chapters[0].end_block == new_boundary
    assert refreshed.chapters[1].start_block == new_boundary


def test_title_edit_matches_when_its_generated_start_moves_back_one_block(tmp_path, monkeypatch):
    source, manifest_path, manifest, reanalysis = _setup(tmp_path)
    original_start = manifest.chapters[1].generated_start_block
    assert original_start is not None and original_start > 0
    manifest.chapters[1].title = "My edited second title"
    write_manifest(manifest_path, manifest)
    original_propose = pipeline.propose_chapters

    def shifted_start(*args, **kwargs):
        proposal = original_propose(*args, **kwargs)
        chapters, _warnings = proposal
        moved = original_start - 1
        chapters[0].end_block = moved
        chapters[1].start_block = moved
        _reset_generated_baselines(chapters)
        return proposal

    monkeypatch.setattr(pipeline, "propose_chapters", shifted_start)
    refreshed = read_manifest(pipeline.analyze_book(source, reanalysis))
    assert refreshed.chapters[1].title == "My edited second title"
    assert refreshed.chapters[1].start_block == original_start - 1


def test_title_edit_survives_a_later_neighbor_boundary_shift(tmp_path, monkeypatch):
    source, manifest_path, manifest, reanalysis = _setup(tmp_path)
    original_start = manifest.chapters[1].generated_start_block
    assert original_start is not None and original_start > 1
    manifest.chapters[1].title = "My edited second title"
    write_manifest(manifest_path, manifest)
    original_propose = pipeline.propose_chapters
    shifts = iter((original_start - 1, original_start - 2))

    def shifted_neighbor(*args, **kwargs):
        proposal = original_propose(*args, **kwargs)
        chapters, _warnings = proposal
        moved = next(shifts)
        chapters[0].end_block = moved
        chapters[1].start_block = moved
        _reset_generated_baselines(chapters)
        return proposal

    monkeypatch.setattr(pipeline, "propose_chapters", shifted_neighbor)
    first = read_manifest(pipeline.analyze_book(source, reanalysis))
    assert first.chapters[1].title == "My edited second title"
    second = read_manifest(pipeline.analyze_book(source, reanalysis))
    assert second.chapters[1].title == "My edited second title"
    assert second.chapters[1].start_block == original_start - 2


def test_edited_chapter_that_becomes_empty_is_reported(tmp_path, monkeypatch):
    source, manifest_path, manifest, reanalysis = _setup(tmp_path)
    manifest.chapters[1].title = "My edited second title"
    write_manifest(manifest_path, manifest)
    original_propose = pipeline.propose_chapters

    def empty_edited_chapter(*args, **kwargs):
        proposal = original_propose(*args, **kwargs)
        chapters, _warnings = proposal
        for block in args[0][chapters[1].start_block : chapters[1].end_block]:
            block.text = "* * *"
        return proposal

    monkeypatch.setattr(pipeline, "propose_chapters", empty_edited_chapter)
    refreshed = read_manifest(pipeline.analyze_book(source, reanalysis))
    assert "empty_chapter" in refreshed.review_required
    assert any("No speakable text" in warning for warning in refreshed.chapters[1].warnings)


def test_moved_unedited_neighbor_is_not_reported_as_an_edit_next_time(tmp_path):
    source, manifest_path, manifest, reanalysis = _setup(tmp_path)
    manifest.chapters[1].start_block += 1
    write_manifest(manifest_path, manifest)

    first = read_manifest(pipeline.analyze_book(source, reanalysis))
    assert first.chapters[0].end_block == first.chapters[1].start_block
    moved_neighbor = first.chapters[0]
    assert moved_neighbor.generated_end_block == moved_neighbor.end_block
    assert moved_neighbor.generated_fingerprint == generated_chapter_fingerprint(moved_neighbor)
    second = read_manifest(pipeline.analyze_book(source, reanalysis))
    assert "Preserved user-edited chapter numbers: 2" in second.warnings
    assert "Preserved user-edited chapter numbers: 1, 2" not in second.warnings


def _reset_generated_baselines(chapters):
    for chapter in chapters:
        chapter.generated_title = chapter.title
        chapter.generated_start_block = chapter.start_block
        chapter.generated_end_block = chapter.end_block
        chapter.generated_voice_id = chapter.voice_id
        chapter.generated_fingerprint = generated_chapter_fingerprint(chapter)
