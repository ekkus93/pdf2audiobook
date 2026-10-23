"""PDF parser and OCR failures must not expose source-derived text."""

import fitz
import pytest

import pdf2audiobook.pdf as pdf
from pdf2audiobook.config import Pdf
from pdf2audiobook.errors import ExtractionError, InputError

PRIVATE = "PRIVATE_SYNTHETIC_PDF_SENTINEL_3481"


def test_pdf_open_failure_redacts_third_party_diagnostics(monkeypatch, tmp_path):
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-1.7 synthetic test bytes")

    def fail_open(*args, **kwargs):
        raise RuntimeError(f"third-party parser saw {PRIVATE}")

    monkeypatch.setattr(pdf.pymupdf, "open", fail_open)
    with pytest.raises(InputError) as raised:
        pdf._open(source)
    assert str(raised.value) == "cannot open PDF; verify file integrity and permissions"
    assert PRIVATE not in str(raised.value)
    assert raised.value.__cause__ is None


def _fixture(tmp_path):
    source = tmp_path / "sample.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((70, 70), "A synthetic chapter with nonprivate text.")
    document.save(source)
    document.close()
    return source


def test_embedded_text_failure_redacts_parser_diagnostics(monkeypatch, tmp_path):
    source = _fixture(tmp_path)

    def fail_lines(*args, **kwargs):
        raise RuntimeError(f"embedded text extraction returned {PRIVATE}")

    monkeypatch.setattr(pdf, "_lines", fail_lines)
    with pytest.raises(ExtractionError) as raised:
        pdf.extract_pdf(source, Pdf(ocr="never"))
    assert "Failed to extract embedded text from PDF page 1" in str(raised.value)
    assert PRIVATE not in str(raised.value)
    assert raised.value.__cause__ is None


def test_ocr_failure_redacts_backend_diagnostics(monkeypatch, tmp_path):
    source = _fixture(tmp_path)

    def fail_ocr(*args, **kwargs):
        raise RuntimeError(f"OCR returned {PRIVATE} from private path")

    monkeypatch.setattr(pdf, "_cached_ocr_lines", fail_ocr)
    with pytest.raises(ExtractionError) as raised:
        pdf.extract_pdf(source, Pdf(ocr="always"))
    assert "OCR failed on PDF page 1" in str(raised.value)
    assert PRIVATE not in str(raised.value)
    assert raised.value.__cause__ is None


def test_backend_cannot_spoof_trusted_ocr_validation(monkeypatch, tmp_path):
    source = _fixture(tmp_path)

    def fail_ocr(*args, **kwargs):
        raise ValueError(f"invalid OCR line geometry or metadata; {PRIVATE}")

    monkeypatch.setattr(pdf, "_cached_ocr_lines", fail_ocr)
    with pytest.raises(ExtractionError) as raised:
        pdf.extract_pdf(source, Pdf(ocr="always"))
    assert "OCR failed on PDF page 1" in str(raised.value)
    assert "invalid OCR line geometry" not in str(raised.value)
    assert PRIVATE not in str(raised.value)
    assert raised.value.__cause__ is None
