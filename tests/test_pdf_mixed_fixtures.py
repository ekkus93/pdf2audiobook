"""Offline PDF fixtures for text, scanned, and mixed-page extraction."""
from __future__ import annotations

from pathlib import Path

import fitz

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import extract_pdf


def _mixed_pdf(path: Path) -> None:
    pdf = fitz.open()
    text = pdf.new_page(width=612, height=792)
    text.insert_text(
        (70, 100),
        "This is a digitally typeset passage with sufficient selectable text.",
    )
    scan = pdf.new_page(width=612, height=792)
    scan.draw_rect(fitz.Rect(70, 90, 520, 150), fill=(0.7, 0.7, 0.7))
    pdf.save(path)
    pdf.close()


def _fake_ocr(calls: list[int]):
    def recognize(page, settings):
        calls.append(page.number)
        return [{
            "text": f"Scanned page {page.number + 1} has an independent readable passage.",
            "bbox": (70.0, 90.0, 510.0, 110.0),
            "font": "OCR",
            "size": 12.0,
        }]
    return recognize


def test_auto_ocr_mixed_pdf_does_not_duplicate_embedded_text(
    monkeypatch, tmp_path: Path
):
    source = tmp_path / "mixed.pdf"
    _mixed_pdf(source)
    calls = []
    monkeypatch.setattr("pdf2audiobook.pdf._ocr_page_lines", _fake_ocr(calls))
    extracted = extract_pdf(source, Pdf(ocr="auto"))
    assert calls == [1]
    assert [span.origin for span in extracted.spans] == ["embedded", "ocr"]
    assert [span.page_index for span in extracted.spans] == [0, 1]
    assert len({span.id for span in extracted.spans}) == 2
    assert len(extracted.blocks) == len(extracted.spans)
    assert all(block.span_ids == [span.id] for block, span in
               zip(extracted.blocks, extracted.spans))


def test_always_ocr_replaces_embedded_layer_instead_of_appending(
    monkeypatch, tmp_path: Path
):
    source = tmp_path / "always.pdf"
    _mixed_pdf(source)
    calls = []
    monkeypatch.setattr("pdf2audiobook.pdf._ocr_page_lines", _fake_ocr(calls))
    extracted = extract_pdf(source, Pdf(ocr="always"))
    assert calls == [0, 1]
    assert len(extracted.spans) == 2
    assert all(span.origin == "ocr" for span in extracted.spans)
    assert not any("digitally typeset" in span.text for span in extracted.spans)


def test_never_ocr_keeps_embedded_page_and_reports_scan(
    monkeypatch, tmp_path: Path
):
    source = tmp_path / "never.pdf"
    _mixed_pdf(source)
    calls = []
    monkeypatch.setattr("pdf2audiobook.pdf._ocr_page_lines", _fake_ocr(calls))
    extracted = extract_pdf(source, Pdf(ocr="never"))
    assert calls == []
    assert len(extracted.spans) == 1
    assert extracted.spans[0].origin == "embedded"
    assert any("no readable text (OCR disabled)" in w for w in extracted.warnings)
