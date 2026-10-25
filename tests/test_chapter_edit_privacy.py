"""A hand-edited range that cannot be preserved fails without source details."""

import fitz

from pdf2audiobook.config import LLM, General, Settings
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
