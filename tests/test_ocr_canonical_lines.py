"""OCR cache misses and hits must expose the same validated line schema."""

import json
from pathlib import Path

import fitz

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import _cached_ocr_lines


def test_ocr_cache_hit_miss_and_disabled_cache_share_allowlisted_schema(
    monkeypatch, tmp_path: Path
):
    doc = fitz.open()
    page = doc.new_page()
    calls = []

    def fake_ocr(page, settings):
        calls.append(page.number)
        return [
            {
                "text": "Recognized source line.",
                "bbox": (50, 90, 210, 105),
                "font": "OCR",
                "size": 12.0,
                "engine_private": {"should_not_escape": True},
            }
        ]

    monkeypatch.setattr("pdf2audiobook.pdf._ocr_page_lines", fake_ocr)
    settings = Pdf(ocr="always")
    cache = tmp_path / "ocr-cache"
    try:
        fresh = _cached_ocr_lines(
            page, settings, cache_dir=cache, input_sha256="test-hash", page_index=0
        )
        hit = _cached_ocr_lines(
            page, settings, cache_dir=cache, input_sha256="test-hash", page_index=0
        )
        uncached = _cached_ocr_lines(
            page, settings, cache_dir=None, input_sha256=None, page_index=0
        )
    finally:
        doc.close()

    assert calls == [0, 0]
    assert fresh == hit == uncached
    assert len(fresh) == 1
    assert set(fresh[0]) == {"text", "bbox", "font", "size"}
    cache_entries = list(cache.glob("*.json"))
    assert len(cache_entries) == 1
    assert set(json.loads(cache_entries[0].read_text())["lines"][0]) == set(fresh[0])
