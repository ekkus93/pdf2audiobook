"""Unmatchable rejected cleanup decisions fail without source text (R87)."""

import fitz
import pytest

import pdf2audiobook.pipeline as pipeline
from pdf2audiobook.config import LLM, General, Settings
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.workspace import read_manifest, write_manifest


def test_unmatched_rejected_page_number_names_chapter_without_source_text(tmp_path, monkeypatch):
    source = tmp_path / "PRIVATE_BOOK.pdf"
    document = fitz.open()
    for number in range(1, 4):
        page = document.new_page(width=600, height=800)
        page.insert_text((80, 80), f"Chapter {number}")
        page.insert_text((80, 130), f"PRIVATE_SOURCE_SENTENCE from chapter {number}.")
        page.insert_text((295, 780), str(number), fontsize=9)
    document.save(source)
    document.close()
    settings = Settings(
        general=General(output_dir=str(tmp_path / "output")),
        llm=LLM(enabled=False),
    )
    settings.pdf.ocr = "never"
    manifest_path = pipeline.analyze_book(source, settings)
    manifest = read_manifest(manifest_path)
    edit = next(item for item in manifest.edits if item.original == "1")
    edit.accepted = False
    write_manifest(manifest_path, manifest)
    monkeypatch.setattr(pipeline, "pagination_cleanup", lambda *_args, **_kwargs: [])
    changed = settings.model_copy(deep=True)
    changed.pdf.ocr = "auto"
    changed.general.resume = False

    with pytest.raises(ExtractionError, match="chapter 1") as error:
        pipeline.analyze_book(source, changed)

    assert "PRIVATE_SOURCE_SENTENCE" not in str(error.value)
    assert "PRIVATE_BOOK" not in str(error.value)
