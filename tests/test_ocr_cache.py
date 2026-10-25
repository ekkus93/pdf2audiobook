"""OCR cache regression tests, using deterministic OCR stubs instead of a model."""

from __future__ import annotations

import json
from pathlib import Path

import fitz

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import extract_pdf


def make_pdf(path: Path, *, text_page: bool = False) -> None:
    document = fitz.open()
    document.new_page()
    if text_page:
        page = document.new_page()
        page.insert_text((60, 90), "Chapter 2 - Embedded text from the next page of the book.")
    document.save(path)
    document.close()


def ocr_stub(calls):
    def run(page, settings):
        calls.append((page.number, settings.ocr_language, settings.ocr_dpi))
        return [
            {"text": "Chapter 1", "bbox": (60, 60, 140, 75), "size": 14.0, "font": "OCR"},
            {
                "text": "A scanned passage.",
                "bbox": (60, 100, 190, 114),
                "size": 12.0,
                "font": "OCR",
            },
        ]

    return run


def test_ocr_cache_reuses_only_scanned_pages(monkeypatch, tmp_path: Path):
    pdf_path = tmp_path / "mixed.pdf"
    make_pdf(pdf_path, text_page=True)
    calls = []
    monkeypatch.setattr("pdf2audiobook.pdf._ocr_page_lines", ocr_stub(calls))
    cache = tmp_path / "ocr-cache"
    settings = Pdf(ocr="auto")
    first = extract_pdf(pdf_path, settings, ocr_cache_dir=cache)
    second = extract_pdf(pdf_path, settings, ocr_cache_dir=cache)
    assert calls == [(0, "eng", 300)]
    assert [(s.id, s.text, s.origin) for s in first.spans] == [
        (s.id, s.text, s.origin) for s in second.spans
    ]
    assert any(s.origin == "ocr" and s.page_index == 0 for s in first.spans)
    assert any(s.origin == "embedded" and s.page_index == 1 for s in first.spans)
    assert len([s for s in first.spans if "Embedded text" in s.text]) == 1


def test_ocr_cache_invalidation_and_corruption(monkeypatch, tmp_path: Path):
    source = tmp_path / "book.pdf"
    make_pdf(source)
    calls = []
    monkeypatch.setattr("pdf2audiobook.pdf._ocr_page_lines", ocr_stub(calls))
    cache = tmp_path / "ocr"
    cfg = Pdf(ocr="always")
    extract_pdf(source, cfg, ocr_cache_dir=cache)
    entries = sorted(cache.glob("*.json"))
    assert len(entries) == 1
    extract_pdf(source, cfg, ocr_cache_dir=cache)
    assert len(calls) == 1

    entries[0].write_text('{"schema_version": 1, "lines": "corrupt"}')
    extract_pdf(source, cfg, ocr_cache_dir=cache)
    assert len(calls) == 2
    assert isinstance(json.loads(entries[0].read_text())["lines"], list)

    cfg.ocr_dpi = 350
    extract_pdf(source, cfg, ocr_cache_dir=cache)
    assert len(calls) == 3
    assert len(list(cache.glob("*.json"))) == 2

    cfg.ocr_language = "fra"
    extract_pdf(source, cfg, ocr_cache_dir=cache)
    assert len(calls) == 4

    # Changing source bytes invalidates all previous OCR keys.
    updated = fitz.open(source)
    updated.new_page()
    revised = tmp_path / "new.pdf"
    updated.save(revised)
    updated.close()
    extract_pdf(revised, cfg, ocr_cache_dir=cache)
    assert len(calls) == 6

    # Explicitly disabling cache still performs OCR.
    extract_pdf(revised, cfg, ocr_cache_dir=None)
    assert len(calls) == 8


def test_deeply_nested_ocr_cache_is_a_miss_and_regenerates(monkeypatch, tmp_path: Path):
    source = tmp_path / "book.pdf"
    make_pdf(source)
    calls = []
    monkeypatch.setattr("pdf2audiobook.pdf._ocr_page_lines", ocr_stub(calls))
    cache = tmp_path / "ocr"
    extract_pdf(source, Pdf(ocr="always"), ocr_cache_dir=cache)
    entry = next(cache.glob("*.json"))
    entry.write_bytes(b"[" * 100_000)
    extract_pdf(source, Pdf(ocr="always"), ocr_cache_dir=cache)
    assert calls == [(0, "eng", 300), (0, "eng", 300)]


def test_empty_ocr_is_retried_not_cached(monkeypatch, tmp_path: Path):
    source = tmp_path / "blank-scan.pdf"
    make_pdf(source)
    cache = tmp_path / "ocr-cache"
    calls = []

    def transient_ocr(page, settings):
        calls.append(page.number)
        if len(calls) == 1:
            return []
        return [
            {
                "text": "Recovered OCR text.",
                "bbox": (60, 100, 220, 114),
                "size": 12.0,
                "font": "OCR",
            },
        ]

    monkeypatch.setattr("pdf2audiobook.pdf._ocr_page_lines", transient_ocr)
    first = extract_pdf(source, Pdf(ocr="always"), ocr_cache_dir=cache)
    assert not first.spans
    assert not list(cache.glob("*.json"))
    second = extract_pdf(source, Pdf(ocr="always"), ocr_cache_dir=cache)
    third = extract_pdf(source, Pdf(ocr="always"), ocr_cache_dir=cache)
    assert len(calls) == 2
    assert second.spans[0].text == third.spans[0].text == "Recovered OCR text."
    assert len(list(cache.glob("*.json"))) == 1
