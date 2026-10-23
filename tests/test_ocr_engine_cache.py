"""OCR cache identity includes the Tesseract engine version."""

from __future__ import annotations

from pathlib import Path

import fitz

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import extract_pdf


def test_tesseract_version_invalidates_page_ocr_cache(monkeypatch, tmp_path: Path):
    source = tmp_path / "scanned.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(source)
    doc.close()
    calls = []
    version = {"value": "tesseract 5.4.0"}
    monkeypatch.setattr("pdf2audiobook.pdf._ocr_engine_version", lambda: version["value"])

    def fake_ocr(page, settings):
        calls.append((page.number, settings.ocr_dpi))
        return [
            {
                "text": "Recognized page contents.",
                "bbox": (55, 80, 200, 100),
                "font": "OCR",
                "size": 11.0,
            }
        ]

    monkeypatch.setattr("pdf2audiobook.pdf._ocr_page_lines", fake_ocr)
    cache = tmp_path / "ocr"
    settings = Pdf(ocr="always")
    first = extract_pdf(source, settings, ocr_cache_dir=cache)
    second = extract_pdf(source, settings, ocr_cache_dir=cache)
    assert len(calls) == 1
    assert first.spans[0].text == second.spans[0].text
    version["value"] = "tesseract 5.5.0"
    third = extract_pdf(source, settings, ocr_cache_dir=cache)
    assert len(calls) == 2
    assert third.spans[0].text == first.spans[0].text
    assert len(list(cache.glob("*.json"))) == 2
