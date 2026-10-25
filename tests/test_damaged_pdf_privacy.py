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
