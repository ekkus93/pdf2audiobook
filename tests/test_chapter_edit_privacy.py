"""A hand-edited range that cannot be preserved fails without source details."""

import fitz
import pytest

from pdf2audiobook.config import LLM, General, Settings
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.workspace import read_manifest, write_manifest


def test_unalignable_edited_chapter_error_contains_no_private_values(tmp_path):
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

    with pytest.raises(ExtractionError) as raised:
        analyze_book(source, settings)
    message = str(raised.value)
    assert "PRIVATE_BOOK_PATH" not in message
    assert "PRIVATE_SOURCE_TEXT" not in message
    assert str(tmp_path) not in message
