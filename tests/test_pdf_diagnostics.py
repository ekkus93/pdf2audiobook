"""Test preservation of printed page labels and Tesseract language diagnostics."""

from pathlib import Path
from types import SimpleNamespace

import fitz

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import (
    extract_pdf,
    missing_ocr_languages,
    tesseract_languages,
)


def test_page_labels_in_provenance(tmp_path: Path):
    source = tmp_path / "labels.pdf"
    document = fitz.open()
    document.new_page().insert_text((80, 120), "A page with an introduction.")
    document.new_page().insert_text((80, 120), "Next page of the book.")
    document.set_page_labels([{"startpage": 0, "style": "r", "firstpagenum": 1}])
    document.save(source)
    document.close()

    extracted = extract_pdf(source, Pdf(ocr="never"))
    assert [span.page_label for span in extracted.spans] == ["i", "ii"]


def test_tesseract_languages_and_missing_language(monkeypatch):
    monkeypatch.setattr("pdf2audiobook.pdf.shutil.which", lambda name: "/bin/tesseract")
    fake = SimpleNamespace(
        returncode=0,
        stdout="List of available languages in /usr/share/tessdata (2):\neng\nfra\n",
        stderr="",
    )
    monkeypatch.setattr("pdf2audiobook.pdf.subprocess.run", lambda *a, **k: fake)
    assert tesseract_languages() == ["eng", "fra"]
    assert missing_ocr_languages("eng+spa", ["eng", "fra"]) == ["spa"]
    assert missing_ocr_languages("eng", None) == ["eng"]
