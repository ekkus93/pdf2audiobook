"""Uncached OCR must obey the same fail-closed geometry contract as cached OCR."""

from pathlib import Path

import fitz
import pytest

from pdf2audiobook.config import Pdf
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.pdf import extract_pdf


def _blank_pdf(path: Path) -> None:
    doc = fitz.open()
    doc.new_page()
    doc.save(path)
    doc.close()


def _line(**changes: object) -> dict:
    item = {
        "text": "A recognized passage.",
        "bbox": (50, 90, 210, 105),
        "size": 12.0,
        "font": "OCR",
    }
    item.update(changes)
    return item


@pytest.mark.parametrize(
    "invalid",
    [
        _line(bbox=(50, 90, 50, 105)),
        _line(bbox=(50, 90, 210, 90)),
        _line(bbox=(float("nan"), 90, 210, 105)),
        _line(bbox=(True, 90, 210, 105)),
        _line(bbox=(50, 90, 210)),
        _line(size=-1),
        _line(size=float("inf")),
        _line(font=42),
        _line(text="  "),
    ],
)
def test_uncached_ocr_rejects_malformed_fresh_lines(monkeypatch, tmp_path: Path, invalid):
    source = tmp_path / "scan.pdf"
    _blank_pdf(source)
    monkeypatch.setattr(
        "pdf2audiobook.pdf._ocr_page_lines",
        lambda page, settings: [invalid],
    )
    with pytest.raises(ExtractionError, match="invalid OCR line geometry or metadata"):
        extract_pdf(source, Pdf(ocr="always"), ocr_cache_dir=None)


def test_uncached_valid_ocr_retains_original_provenance(monkeypatch, tmp_path: Path):
    source = tmp_path / "scan.pdf"
    _blank_pdf(source)
    monkeypatch.setattr(
        "pdf2audiobook.pdf._ocr_page_lines",
        lambda page, settings: [_line()],
    )
    result = extract_pdf(source, Pdf(ocr="always"), ocr_cache_dir=None)
    assert len(result.spans) == len(result.blocks) == 1
    assert result.spans[0].text == result.blocks[0].text == "A recognized passage."
    assert result.spans[0].origin == "ocr"
    assert result.spans[0].id == result.blocks[0].id
    assert result.spans[0].bbox == (50, 90, 210, 105)


def test_uncached_empty_ocr_is_reviewable_not_an_error(monkeypatch, tmp_path: Path):
    source = tmp_path / "scan.pdf"
    _blank_pdf(source)
    monkeypatch.setattr(
        "pdf2audiobook.pdf._ocr_page_lines",
        lambda page, settings: [],
    )
    result = extract_pdf(source, Pdf(ocr="always"), ocr_cache_dir=None)
    assert result.spans == []
    assert result.blocks == []
    assert any("OCR produced no text" in warning for warning in result.warnings)
