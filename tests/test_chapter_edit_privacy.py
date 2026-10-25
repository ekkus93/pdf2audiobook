"""A hand-edited range that cannot be preserved fails without source details."""

import fitz
import pytest

from pdf2audiobook.config import LLM, General, Settings
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.models import Chapter
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.workspace import read_manifest, write_manifest


def test_boundary_edit_moves_neighboring_boundary_without_private_diagnostics(tmp_path):
    source = tmp_path / "PRIVATE_BOOK_PATH.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 80), "Chapter 1")
    page.insert_text((72, 120), "PRIVATE_SOURCE_TEXT from first chapter.")
    page.insert_text((72, 180), "Chapter 2")
    page.insert_text((72, 220), "PRIVATE_SOURCE_TEXT from second chapter.")
    document.save(source)
    document.close()

    settings = Settings(
        general=General(output_dir=str(tmp_path / "output")),
        llm=LLM(enabled=False),
    )
    manifest_path = analyze_book(source, settings)
    manifest = read_manifest(manifest_path)
    manifest.chapters[0].title = "Edited title"
    manifest.chapters[0].end_block -= 1
    write_manifest(manifest_path, manifest)
    settings.general.resume = False

    refreshed = read_manifest(analyze_book(source, settings))
    assert refreshed.chapters[0].title == "Edited title"
    assert refreshed.chapters[0].end_block == refreshed.chapters[1].start_block


def test_unalignable_hand_edit_conflict_is_private_and_gives_next_step(tmp_path, monkeypatch):
    source = tmp_path / "PRIVATE_BOOK_PATH.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 80), "Chapter 1")
    page.insert_text((72, 120), "PRIVATE_SOURCE_TEXT from the first chapter.")
    page.insert_text((72, 180), "Chapter 2")
    page.insert_text((72, 220), "PRIVATE_SOURCE_TEXT from the second chapter.")
    document.save(source)
    document.close()
    settings = Settings(
        general=General(output_dir=str(tmp_path / "output")),
        llm=LLM(enabled=False),
    )
    manifest_path = analyze_book(source, settings)
    manifest = read_manifest(manifest_path)
    manifest.chapters[1].title = "Private edited chapter title"
    write_manifest(manifest_path, manifest)

    def merged(blocks, *_args, **_kwargs):
        return [
            Chapter(
                id="c0001",
                number=1,
                title="Everything",
                start_block=0,
                end_block=len(blocks),
                confidence=0.9,
            )
        ], []

    monkeypatch.setattr("pdf2audiobook.pipeline.propose_chapters", merged)
    settings.general.resume = False
    with pytest.raises(ExtractionError) as error:
        analyze_book(source, settings)
    message = str(error.value)
    assert "Chapter 2" in message
    assert "approve or revert" in message
    assert "PRIVATE_BOOK_PATH" not in message
    assert "PRIVATE_SOURCE_TEXT" not in message
    assert str(tmp_path) not in message
