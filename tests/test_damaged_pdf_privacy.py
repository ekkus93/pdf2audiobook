"""Damaged PDFs are content-free review gates before any synthesis starts."""

import fitz
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.config import LLM, General, Pdf, Settings
from pdf2audiobook.pipeline import analyze_book


def _truncated_book(path):
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 80), "Chapter 1")
    page.insert_text((72, 120), "PRIVATE_SOURCE_TEXT that must never appear in diagnostics.")
    document.save(path)
    document.close()
    path.write_bytes(path.read_bytes()[:-100])


def test_repaired_pdf_is_marked_for_review_and_conversion_is_private(tmp_path):
    source = tmp_path / "PRIVATE_BOOK_NAME.pdf"
    _truncated_book(source)
    settings = Settings(
        general=General(output_dir=str(tmp_path / "analysis")),
        pdf=Pdf(ocr="never"),
        llm=LLM(enabled=False),
    )
    manifest_path = analyze_book(source, settings)
    from pdf2audiobook.workspace import read_manifest

    manifest = read_manifest(manifest_path)
    warning = "source PDF was damaged and repaired; verify page coverage"
    assert warning in manifest.warnings
    assert manifest.review_required == ["damaged_source"]

    result = CliRunner().invoke(
        app,
        [
            "convert",
            str(source),
            "--no-config",
            "--no-llm",
            "--output",
            str(tmp_path / "conversion"),
        ],
    )
    assert result.exit_code == 6
    assert "damaged source" in result.stderr
    assert "PRIVATE_BOOK_NAME" not in result.stderr
    assert "PRIVATE_SOURCE_TEXT" not in result.stderr


def test_explicit_damaged_source_acknowledgement_is_persisted(tmp_path, monkeypatch):
    from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock
    from pdf2audiobook.pipeline import convert_book
    from pdf2audiobook.workspace import read_manifest, write_manifest

    source = tmp_path / "source.pdf"
    source.write_bytes(b"synthetic")
    folder = tmp_path / "workspace"
    folder.mkdir()
    manifest_path = folder / "manifest.json"
    manifest = BookManifest(
        schema_version=3,
        input_sha256="x",
        title="Book",
        source_path="source.pdf",
        blocks=[DocumentBlock(id="b", text="Text.", page_index=0)],
        chapters=[
            Chapter(id="c", number=1, title="Chapter", start_block=0, end_block=1, confidence=1)
        ],
        review_required=["damaged_source"],
    )
    write_manifest(manifest_path, manifest)
    monkeypatch.setattr("pdf2audiobook.pipeline.analyze_book", lambda *_a, **_k: manifest_path)
    monkeypatch.setattr("pdf2audiobook.pipeline.select_chapters", lambda *_a, **_k: [])
    convert_book(source, Settings(), accept_review=("damaged_source",))
    saved = read_manifest(manifest_path)
    assert saved.review_required == []
    assert saved.review_acknowledged == ["damaged_source"]
