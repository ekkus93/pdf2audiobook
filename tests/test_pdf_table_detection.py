"""Non-destructive table detection with synthetic vector-grid PDFs."""
from pathlib import Path

import fitz

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import extract_pdf


def test_grid_table_warns_without_dropping_cells(tmp_path: Path):
    source = tmp_path / "table.pdf"
    document = fitz.open()
    page = document.new_page()
    for x in (50, 180, 310):
        page.draw_line((x, 100), (x, 220), color=(0, 0, 0), width=1)
    for y in (100, 140, 180, 220):
        page.draw_line((50, y), (310, y), color=(0, 0, 0), width=1)
    expected = []
    for row, y in enumerate((120, 160, 200), 1):
        for col, x in enumerate((60, 190), 1):
            cell = f"Cell {row} {col}"
            expected.append(cell)
            page.insert_text((x, y), cell, fontsize=10)
    document.save(source)
    document.close()

    result = extract_pdf(source, Pdf(ocr="never"))
    assert any("possible table detected" in warning for warning in result.warnings)
    assert all(any(cell in span.text for span in result.spans) for cell in expected)
    assert all(span.origin == "embedded" for span in result.spans)


def test_prose_page_has_no_table_warning(tmp_path: Path):
    source = tmp_path / "prose.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((55, 120), "Ordinary paragraph without a table.", fontsize=12)
    document.save(source)
    document.close()

    result = extract_pdf(source, Pdf(ocr="never"))
    assert not any("table detected" in warning for warning in result.warnings)
