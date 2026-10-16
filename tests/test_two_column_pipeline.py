"""Integration coverage for conservative two-column PDF reading order."""
from __future__ import annotations

from pathlib import Path

import fitz

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import extract_pdf


def _make_two_column_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    for n in range(5):
        y = 100 + n * 24
        page.insert_text((50, y), f"Left passage number {n} with sustained text.")
        page.insert_text((335, y), f"Right passage number {n} with sustained text.")
    doc.save(path)
    doc.close()


def _expected() -> list[str]:
    return [
        *(f"Left passage number {n} with sustained text." for n in range(5)),
        *(f"Right passage number {n} with sustained text." for n in range(5)),
    ]


def test_embedded_columns_flow_into_blocks_without_loss(tmp_path: Path) -> None:
    source = tmp_path / "columns.pdf"
    _make_two_column_pdf(source)
    first = extract_pdf(source, Pdf(ocr="never"))
    second = extract_pdf(source, Pdf(ocr="never"))
    expected = _expected()
    assert [span.text for span in first.spans] == expected
    assert [block.text for block in first.blocks] == expected
    assert [span.id for span in first.spans] == [span.id for span in second.spans]
    assert [block.order for block in first.blocks] == list(range(10))
    assert all(span.origin == "embedded" and span.bbox for span in first.spans)
    assert any("reconstructed two-column" in message for message in first.warnings)


def test_ocr_columns_share_ordering_and_provenance(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "scanned.pdf"
    doc = fitz.open()
    doc.new_page(width=600, height=800)
    doc.save(source)
    doc.close()
    rows = []
    for n in range(5):
        for x, side in ((50, "Left"), (335, "Right")):
            rows.append({
                "text": f"{side} passage number {n} with sustained text.",
                "bbox": (x, 100 + n * 24, x + 180, 112 + n * 24),
                "font": "OCR",
                "size": 12.0,
            })
    monkeypatch.setattr(
        "pdf2audiobook.pdf._ocr_page_lines",
        lambda page, settings: list(rows),
    )
    result = extract_pdf(source, Pdf(ocr="always"))
    assert [span.text for span in result.spans] == _expected()
    assert all(span.origin == "ocr" and span.page_index == 0 for span in result.spans)
    assert [block.span_ids for block in result.blocks] == [
        [span.id] for span in result.spans
    ]


def test_single_column_is_not_reordered(tmp_path: Path) -> None:
    source = tmp_path / "single.pdf"
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    for n in range(10):
        page.insert_text(
            (50, 100 + n * 24),
            f"Single column paragraph line {n} with sufficient text.",
        )
    doc.save(source)
    doc.close()
    result = extract_pdf(source, Pdf(ocr="never"))
    assert [span.text for span in result.spans] == [
        f"Single column paragraph line {n} with sufficient text."
        for n in range(10)
    ]
    assert not any("reconstructed two-column" in msg for msg in result.warnings)
