"""Fail closed on malformed OCR geometry in fresh and cached recognition."""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from pdf2audiobook.config import Pdf
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.pdf import _valid_cached_lines, extract_pdf


def _line(bbox=(40, 50, 120, 64)):
    return {"text": "Recovered scanned text", "bbox": bbox, "font": "OCR", "size": 12.0}


def _blank_pdf(path: Path) -> None:
    document = fitz.open()
    document.new_page()
    document.save(path)
    document.close()


@pytest.mark.parametrize(
    "bbox",
    [
        (40, 50, 40, 64),
        (40, 50, 120, 50),
        (121, 50, 120, 64),
        (40, 65, 120, 64),
        (True, 50, 120, 64),
        (float("nan"), 50, 120, 64),
        (40, float("inf"), 120, 64),
    ],
)
def test_cached_ocr_rejects_degenerate_or_nonfinite_boxes(bbox):
    assert _valid_cached_lines({"schema_version": 1, "lines": [_line(bbox)]}) is None


def test_cached_ocr_accepts_valid_text_and_geometry():
    data = {"schema_version": 1, "lines": [_line()]}
    assert _valid_cached_lines(data) == [_line([40, 50, 120, 64])]
    assert data["lines"][0]["bbox"] == (40, 50, 120, 64)


def test_degenerate_cached_geometry_triggers_fresh_recognition(monkeypatch, tmp_path: Path):
    source = tmp_path / "scan.pdf"
    _blank_pdf(source)
    calls = []

    def recognize(page, settings):
        calls.append(page.number)
        return [_line()]

    monkeypatch.setattr("pdf2audiobook.pdf._ocr_page_lines", recognize)
    cache = tmp_path / "cache"
    extract_pdf(source, Pdf(ocr="always"), ocr_cache_dir=cache)
    (entry,) = cache.glob("*.json")
    data = json.loads(entry.read_text())
    data["lines"][0]["bbox"] = [40, 50, 40, 64]
    entry.write_text(json.dumps(data))
    recovered = extract_pdf(source, Pdf(ocr="always"), ocr_cache_dir=cache)
    assert calls == [0, 0]
    assert recovered.spans[0].text == "Recovered scanned text"
    assert json.loads(entry.read_text())["lines"][0]["bbox"] == [40, 50, 120, 64]


def test_invalid_fresh_ocr_fails_without_poisoning_cache(monkeypatch, tmp_path: Path):
    source = tmp_path / "scan.pdf"
    _blank_pdf(source)
    monkeypatch.setattr(
        "pdf2audiobook.pdf._ocr_page_lines",
        lambda page, settings: [_line((40, 50, 40, 64))],
    )
    cache = tmp_path / "cache"
    with pytest.raises(ExtractionError, match="invalid OCR line geometry"):
        extract_pdf(source, Pdf(ocr="always"), ocr_cache_dir=cache)
    assert not list(cache.glob("*.json"))
