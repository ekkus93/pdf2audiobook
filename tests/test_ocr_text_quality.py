"""OCR auto-mode must not trust a long but damaged selectable-text layer."""
from pathlib import Path

import fitz

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import extract_pdf


def pdf_file(path: Path) -> None:
    doc = fitz.open()
    doc.new_page().insert_text(
        (70, 110), "A sufficiently long and normally readable PDF sentence."
    )
    doc.save(path)
    doc.close()


def test_auto_ocr_on_damaged_selectable_text(monkeypatch, tmp_path: Path):
    path = tmp_path / "damaged.pdf"
    pdf_file(path)
    damaged = "Long but damaged text " + "\ufffd" * 20 + " ending here."
    monkeypatch.setattr(
        "pdf2audiobook.pdf._lines",
        lambda page, textpage=None: [
            {"text": damaged, "bbox": (70, 90, 420, 105),
             "font": "Broken", "size": 12}
        ],
    )
    calls = []

    def fake_ocr(page, settings):
        calls.append(page.number)
        return [{"text": "Recognized prose from the scanned page.",
                 "bbox": (70, 90, 420, 105), "font": "OCR", "size": 12}]

    monkeypatch.setattr("pdf2audiobook.pdf._ocr_page_lines", fake_ocr)
    result = extract_pdf(path, Pdf(ocr="auto"))
    assert calls == [0]
    assert len(result.spans) == 1
    assert result.spans[0].origin == "ocr"
    assert "Recognized prose" in result.spans[0].text
    assert any("damaged embedded text layer" in w for w in result.warnings)


def test_never_mode_preserves_damaged_source_for_review(monkeypatch, tmp_path: Path):
    path = tmp_path / "damaged.pdf"
    pdf_file(path)
    damaged = "Damaged text " + "\ufffd" * 20
    monkeypatch.setattr(
        "pdf2audiobook.pdf._lines",
        lambda page, textpage=None: [
            {"text": damaged, "bbox": (70, 90, 420, 105),
             "font": "Broken", "size": 12}
        ],
    )
    monkeypatch.setattr(
        "pdf2audiobook.pdf._ocr_page_lines",
        lambda *args: (_ for _ in ()).throw(AssertionError("OCR not allowed")),
    )
    result = extract_pdf(path, Pdf(ocr="never"))
    assert result.spans[0].text == damaged
    assert result.spans[0].origin == "embedded"
    assert any("suspicious replacement" in w for w in result.warnings)


def test_auto_preserves_valid_embedded_text(monkeypatch, tmp_path: Path):
    path = tmp_path / "good.pdf"
    pdf_file(path)
    monkeypatch.setattr(
        "pdf2audiobook.pdf._ocr_page_lines",
        lambda *args: (_ for _ in ()).throw(AssertionError("unneeded OCR")),
    )
    result = extract_pdf(path, Pdf(ocr="auto"))
    assert len(result.spans) == 1
    assert result.spans[0].origin == "embedded"
