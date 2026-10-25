"""Analysis cache identity excludes operational values and reports safe stages."""

import fitz
import pytest

from pdf2audiobook.config import LLM, General, Settings
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.review_ui import save_chapter_updates
from pdf2audiobook.workspace import read_manifest


def _prepared(tmp_path):
    source = tmp_path / "PRIVATE_BOOK_NAME.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 80), "Chapter 1")
    page.insert_text((72, 120), "PRIVATE_SOURCE_TEXT with a synthetic passage.")
    document.save(source)
    document.close()
    settings = Settings(
        general=General(output_dir=str(tmp_path / "output")),
        llm=LLM(enabled=False),
        chapters={"allow_single_chapter": True},
    )
    manifest_path = analyze_book(source, settings)
    return source, settings, manifest_path


def _approve_in_review_ui(manifest_path):
    manifest = read_manifest(manifest_path)
    save_chapter_updates(
        manifest_path,
        [
            {
                "id": chapter.id,
                "title": chapter.title,
                "start_block": chapter.start_block,
                "end_block": chapter.end_block,
            }
            for chapter in manifest.chapters
        ],
    )


def test_operational_settings_do_not_invalidate_approved_analysis(tmp_path):
    source, settings, manifest_path = _prepared(tmp_path)
    _approve_in_review_ui(manifest_path)
    settings.llm.max_requests = 3
    settings.chapters.allow_single_chapter = False
    assert analyze_book(source, settings) == manifest_path


def test_approved_analysis_names_changed_stage_without_private_values(tmp_path):
    source, settings, manifest_path = _prepared(tmp_path)
    _approve_in_review_ui(manifest_path)
    settings.pdf.ocr_language = "fra"
    with pytest.raises(ExtractionError) as raised:
        analyze_book(source, settings)
    message = str(raised.value)
    assert "Changed analysis stage(s): extraction" in message
    assert "PRIVATE_BOOK_NAME" not in message
    assert "PRIVATE_SOURCE_TEXT" not in message
    assert str(tmp_path) not in message
    assert "fra" not in message
