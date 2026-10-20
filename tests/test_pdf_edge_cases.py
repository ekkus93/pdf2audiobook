"""Deterministic malformed, encrypted, rotated and blank PDF acceptance."""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pdf2audiobook.config import Pdf
from pdf2audiobook.errors import ExtractionError, InputError
from pdf2audiobook.pdf import extract_pdf, inspect_pdf


def test_rotated_pdf_uses_unrotated_text_geometry(tmp_path: Path):
    source = tmp_path / "rotated.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((75, 110), "Chapter 1")
    page.insert_text((75, 150), "This is embedded text on a rotated page.")
    page.set_rotation(90)
    document.new_page(width=595, height=842)
    document.save(source)
    document.close()

    info = inspect_pdf(source)
    assert info["pages"] == 2
    assert info["page_rotations"] == [90, 0]
    assert info["page_sizes"] == [(595.0, 842.0), (595.0, 842.0)]

    result = extract_pdf(source, Pdf(ocr="never"))
    assert result.page_sizes == [(595.0, 842.0), (595.0, 842.0)]
    assert len(result.spans) == 2
    assert all(span.page_index == 0 and span.origin == "embedded" for span in result.spans)
    assert all(span.bbox and span.bbox[1] < 160 for span in result.spans)
    assert any("Page 2: no readable text" in warning for warning in result.warnings)


def test_malformed_pdf_is_domain_error_even_with_ocr_cache(tmp_path: Path):
    source = tmp_path / "corrupt.pdf"
    source.write_bytes(b"%PDF-1.7\nnot a valid PDF file\n")
    with pytest.raises(InputError, match="cannot open PDF"):
        inspect_pdf(source)
    with pytest.raises(InputError, match="cannot open PDF"):
        extract_pdf(source, Pdf(ocr="auto"), ocr_cache_dir=tmp_path / "ocr")

    missing = tmp_path / "missing.pdf"
    with pytest.raises(InputError, match="not a readable PDF"):
        extract_pdf(missing, Pdf(ocr="never"))


def test_password_protected_pdf_requires_correct_env(monkeypatch, tmp_path: Path):
    source = tmp_path / "protected.pdf"
    document = fitz.open()
    document.new_page().insert_text((72, 120), "Secret PDF page for local testing.")
    document.save(
        source,
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="test-owner-pass",
        user_pw="test-user-pass",
    )
    document.close()

    with pytest.raises(InputError, match="PDF requires a valid password") as missing:
        extract_pdf(source, Pdf(ocr="never"))
    assert "test-user-pass" not in str(missing.value)
    monkeypatch.setenv("BOOK_PDF_PASS", "wrong-password")
    with pytest.raises(InputError, match="PDF requires a valid password") as wrong:
        inspect_pdf(source, password_env="BOOK_PDF_PASS")
    assert "wrong-password" not in str(wrong.value)

    monkeypatch.setenv("BOOK_PDF_PASS", "test-user-pass")
    info = inspect_pdf(source, password_env="BOOK_PDF_PASS")
    assert info["pages"] == 1
    result = extract_pdf(source, Pdf(ocr="never", password_env="BOOK_PDF_PASS"))
    assert len(result.spans) == 1
    assert result.spans[0].text == "Secret PDF page for local testing."


def test_page_text_failure_reports_page_number(monkeypatch, tmp_path: Path):
    source = tmp_path / "broken-page.pdf"
    document = fitz.open()
    document.new_page().insert_text((72, 120), "A valid page.")
    document.save(source)
    document.close()

    def fail_text(*args, **kwargs):
        raise RuntimeError("broken page text stream")

    monkeypatch.setattr("pdf2audiobook.pdf._lines", fail_text)
    with pytest.raises(ExtractionError, match="Failed to extract embedded text from PDF page 1") as failure:
        extract_pdf(source, Pdf(ocr="never"))
    assert "broken page text stream" not in str(failure.value)
