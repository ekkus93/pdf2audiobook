"""Characterization of the hand-edit merge in `_analyze_book_locked` (split spec S3/S11).

Each test pins today's behaviour for one branch of the merge that no other test
reaches, so splitting the function cannot change it unnoticed.
"""

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
    page.insert_text((72, 150), "Another paragraph in the first chapter.")
    page.insert_text((72, 180), "Chapter 2")
    page.insert_text((72, 220), "Second chapter contains more readable prose.")
    page.insert_text((72, 250), "A further paragraph closes the second chapter.")
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


def _conflict(source, settings):
    with pytest.raises(ExtractionError) as error:
        pipeline.analyze_book(source, settings)
    return str(error.value)


def test_edited_owner_of_a_shared_match_is_named(tmp_path, monkeypatch):
    source, manifest_path, manifest, reanalysis = _setup(tmp_path)
    manifest.chapters[0].title = "My edited first title"
    write_manifest(manifest_path, manifest)
    monkeypatch.setattr(
        pipeline,
        "propose_chapters",
        lambda blocks, *_a, **_k: ([_chapter(1, "Everything", 0, len(blocks))], []),
    )

    message = _conflict(source, reanalysis)

    assert message.startswith("Chapter 1 was edited but cannot be aligned")
    assert "My edited first title" not in message


def test_two_edited_chapters_sharing_a_match_name_both(tmp_path, monkeypatch):
    source, manifest_path, manifest, reanalysis = _setup(tmp_path)
    manifest.chapters[0].title = "First edit"
    manifest.chapters[1].title = "Second edit"
    write_manifest(manifest_path, manifest)
    monkeypatch.setattr(
        pipeline,
        "propose_chapters",
        lambda blocks, *_a, **_k: ([_chapter(1, "Everything", 0, len(blocks))], []),
    )

    message = _conflict(source, reanalysis)

    assert message.startswith("Edited chapters cannot be uniquely matched")
    assert "edit" not in message.split(";")[0].lower().replace("edited", "")


def test_edited_chapter_with_no_containing_new_chapter_is_a_conflict(tmp_path, monkeypatch):
    source, manifest_path, manifest, reanalysis = _setup(tmp_path)
    manifest.chapters[1].title = "Second edit"
    write_manifest(manifest_path, manifest)
    monkeypatch.setattr(
        pipeline,
        "propose_chapters",
        lambda blocks, *_a, **_k: ([_chapter(1, "Only the start", 0, 1)], []),
    )

    message = _conflict(source, reanalysis)

    assert message.startswith("Chapter 2 was edited but cannot be aligned")


def test_edited_owner_of_a_match_shared_with_an_unedited_chapter_is_named(tmp_path, monkeypatch):
    source, manifest_path, manifest, reanalysis = _setup(tmp_path)
    manifest.chapters[0].title = "First edit"
    write_manifest(manifest_path, manifest)
    monkeypatch.setattr(
        pipeline,
        "propose_chapters",
        lambda blocks, *_a, **_k: ([_chapter(1, "Generated", 0, len(blocks))], []),
    )

    message = _conflict(source, reanalysis)

    assert message.startswith("Chapter 1 was edited but cannot be aligned")


def test_unedited_chapter_without_a_match_is_skipped(tmp_path):
    source, manifest_path, manifest, reanalysis = _setup(tmp_path)
    manifest.chapters[1].title = "Second edit"
    # The old first chapter's heading block no longer exists in the new
    # extraction, so that unedited chapter has no match and is skipped.
    manifest.blocks[0].id = "heading-from-an-older-extraction"
    write_manifest(manifest_path, manifest)

    result = read_manifest(pipeline.analyze_book(source, reanalysis))

    assert [chapter.title for chapter in result.chapters] == ["Chapter 1", "Second edit"]
    assert "Preserved user-edited chapter numbers: 2" in result.warnings


def test_merge_range_guard_rejects_an_edited_chapter_outside_the_old_blocks(tmp_path):
    """The guard behind manifest validation: an out-of-range edit is a conflict."""
    _, _, manifest, _ = _setup(tmp_path)
    total = len(manifest.blocks)
    edited = manifest.chapters[1].model_copy(update={"title": "Edit", "start_block": total})
    merge = pipeline._HandEditMerge(
        existing_manifest=manifest,
        new_positions={block.id: i for i, block in enumerate(manifest.blocks)},
        new_block_count=total,
        old_chapters=[manifest.chapters[0], edited],
        edited_by_id={edited.id: edited},
        matches={chapter.id: chapter for chapter in manifest.chapters},
        changed_chapter_numbers={edited.number},
    )

    with pytest.raises(ExtractionError) as error:
        pipeline._queue_hand_edits(merge)

    assert str(error.value).startswith("Chapter 2 was edited but cannot be aligned")
    assert merge.field_changes == {}


def test_inconsistent_edits_to_a_shared_boundary_conflict(tmp_path):
    source, manifest_path, manifest, reanalysis = _setup(tmp_path)
    boundary = manifest.chapters[1].start_block
    manifest.chapters[0].end_block = boundary + 1
    manifest.chapters[1].start_block = boundary - 1
    write_manifest(manifest_path, manifest)

    message = _conflict(source, reanalysis)

    assert message.startswith("Edited boundaries conflict")


def test_edited_start_beyond_the_old_blocks_is_rejected_when_the_manifest_is_read(tmp_path):
    source, manifest_path, manifest, reanalysis = _setup(tmp_path)
    manifest.chapters[1].start_block = len(manifest.blocks)
    write_manifest(manifest_path, manifest)

    # Manifest validation rejects the range before the merge's own range guard
    # runs; that guard is tested directly above.
    message = _conflict(source, reanalysis)

    assert message == (
        "Cannot read or validate audiobook manifest; re-run analyze with a new output directory"
    )


def test_edited_end_at_the_last_block_maps_to_the_new_end(tmp_path):
    source, manifest_path, manifest, reanalysis = _setup(tmp_path)
    total = len(manifest.blocks)
    manifest.chapters[0].end_block = total
    write_manifest(manifest_path, manifest)

    message = _conflict(source, reanalysis)

    # The first chapter's end maps to the new document end, which would move the
    # second chapter's start to the end and leave it empty.
    assert message == (
        "Edited boundary between chapters 1 and 2 cannot be aligned; "
        "approve or revert the named chapter(s)."
    )


def test_edited_start_whose_neighbor_has_no_match_is_a_conflict(tmp_path, monkeypatch):
    source, manifest_path, manifest, reanalysis = _setup(tmp_path)
    second_start = manifest.chapters[1].start_block
    manifest.chapters[1].start_block = second_start + 1
    write_manifest(manifest_path, manifest)
    monkeypatch.setattr(
        pipeline,
        "propose_chapters",
        lambda blocks, *_a, **_k: ([_chapter(1, "Second only", second_start, len(blocks))], []),
    )

    message = _conflict(source, reanalysis)

    assert message.startswith("Edited boundary neighbor cannot be aligned")


def _three_chapter_source(path):
    document = fitz.open()
    page = document.new_page()
    y = 80
    for number in (1, 2, 3):
        page.insert_text((72, y), f"Chapter {number}")
        page.insert_text((72, y + 40), f"Readable prose for chapter number {number} goes here.")
        page.insert_text((72, y + 70), "Another paragraph keeps the chapter long enough.")
        y += 140
    document.save(path)
    document.close()


def test_two_unedited_chapters_sharing_a_match_are_skipped(tmp_path, monkeypatch):
    source = tmp_path / "book.pdf"
    _three_chapter_source(source)
    settings = Settings(general=General(output_dir=str(tmp_path / "out")), llm=LLM(enabled=False))
    manifest_path = pipeline.analyze_book(source, settings)
    manifest = read_manifest(manifest_path)
    assert len(manifest.chapters) == 3
    third_start = manifest.chapters[2].start_block
    manifest.chapters[2].title = "Third edit"
    write_manifest(manifest_path, manifest)
    reanalysis = settings.model_copy(
        update={"general": General(output_dir=str(tmp_path / "out"), resume=False)}
    )
    monkeypatch.setattr(
        pipeline,
        "propose_chapters",
        lambda blocks, *_a, **_k: (
            [_chapter(1, "Merged", 0, third_start), _chapter(2, "Third", third_start, len(blocks))],
            [],
        ),
    )

    refreshed = read_manifest(pipeline.analyze_book(source, reanalysis))

    assert [chapter.title for chapter in refreshed.chapters] == ["Merged", "Third edit"]


def test_edited_start_on_a_block_that_no_longer_exists_is_a_conflict(tmp_path, monkeypatch):
    source, manifest_path, manifest, reanalysis = _setup(tmp_path)
    second_start = manifest.chapters[1].start_block
    manifest.chapters[0].end_block = second_start + 1
    manifest.chapters[1].start_block = second_start + 1
    write_manifest(manifest_path, manifest)
    original_extract = pipeline.extract_pdf

    def extract_with_renamed_block(*args, **kwargs):
        extracted = original_extract(*args, **kwargs)
        extracted.blocks[second_start + 1].id = "renamed-block"
        return extracted

    monkeypatch.setattr(pipeline, "extract_pdf", extract_with_renamed_block)

    message = _conflict(source, reanalysis)

    # Chapter 1's edited end is mapped first, so it is the one named.
    assert message == (
        "Chapter 1 boundary cannot be aligned for chapter(s) 1; "
        "approve or revert the named chapter(s)."
    )
