"""Empty automatic OCR must not silently discard available embedded prose."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import extract_pdf


def _short_text_pdf(path: Path) -> None:
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=300)
        page.insert_text((45, 70), "Chapter 7", fontsize=16)
        doc.save(path)


@pytest.mark.parametrize("mode", ["auto", "always", "never"])
def test_empty_ocr_preserves_short_embedded_prose_only_in_auto_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    source = tmp_path / "short-heading.pdf"
    _short_text_pdf(source)
    calls = []

    def empty_ocr(*args, **kwargs):
        calls.append(True)
        return []

    monkeypatch.setattr("pdf2audiobook.pdf._cached_ocr_lines", empty_ocr)
    result = extract_pdf(source, Pdf(ocr=mode))
    assert bool(calls) is (mode != "never")
    if mode == "always":
        assert not result.spans
        assert any("OCR produced no text" in warning for warning in result.warnings)
    else:
        assert len(result.spans) == len(result.blocks) == 1
        assert result.spans[0].text == result.blocks[0].text == "Chapter 7"
        assert result.spans[0].origin == "embedded"
        assert result.spans[0].bbox is not None
    if mode == "auto":
        assert any("retained unverified embedded text" in warning for warning in result.warnings)
    else:
        assert not any(
            "retained unverified embedded text" in warning for warning in result.warnings
        )


def test_auto_ocr_empty_on_scanned_page_still_reports_no_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "blank.pdf"
    with fitz.open() as doc:
        doc.new_page(width=400, height=300)
        doc.save(source)
    monkeypatch.setattr("pdf2audiobook.pdf._cached_ocr_lines", lambda *a, **k: [])
    result = extract_pdf(source, Pdf(ocr="auto"))
    assert not result.spans
    assert any("OCR produced no text" in warning for warning in result.warnings)
    assert not any("retained unverified embedded text" in warning for warning in result.warnings)
