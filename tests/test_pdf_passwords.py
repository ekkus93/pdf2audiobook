from pathlib import Path

import fitz
import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.config import Pdf, Settings
from pdf2audiobook.errors import InputError
from pdf2audiobook.pdf import extract_pdf, inspect_pdf
from pdf2audiobook.pipeline import analyze_book


def encrypted_fixture(path: Path):
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((70, 70), "Chapter 1")
    page.insert_text((70, 120), "A secret but permitted story.")
    pdf.save(
        path,
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner-secret",
        user_pw="reader-secret",
    )
    pdf.close()


def test_encrypted_pdf_uses_password_environment_without_leak(monkeypatch, tmp_path):
    source = tmp_path / "protected.pdf"
    encrypted_fixture(source)
    with pytest.raises(InputError, match="valid password"):
        inspect_pdf(source)
    monkeypatch.setenv("BOOK_PDF_PASSWORD", "reader-secret")
    assert inspect_pdf(source, password_env="BOOK_PDF_PASSWORD")["pages"] == 1
    assert (
        "Chapter"
        in extract_pdf(source, Pdf(ocr="never", password_env="BOOK_PDF_PASSWORD")).blocks[0].text
    )
    settings = Settings()
    settings.pdf.ocr = "never"
    settings.pdf.password_env = "BOOK_PDF_PASSWORD"
    settings.llm.enabled = False
    settings.general.output_dir = str(tmp_path / "out")
    manifest_path = analyze_book(source, settings)
    assert manifest_path.exists()
    assert "reader-secret" not in manifest_path.read_text()


def test_encrypted_pdf_cli_override(monkeypatch, tmp_path):
    source = tmp_path / "protected.pdf"
    encrypted_fixture(source)
    monkeypatch.setenv("BOOK_PDF_PASSWORD", "reader-secret")
    result = CliRunner().invoke(
        app,
        [
            "analyze",
            str(source),
            "--no-llm",
            "--ocr",
            "never",
            "--pdf-password-env",
            "BOOK_PDF_PASSWORD",
            "--output",
            str(tmp_path / "out"),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "reader-secret" not in result.output
