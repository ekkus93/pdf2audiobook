"""Corrupt OCR cache and unusual Tesseract CLI output must fail closed."""
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import _ocr_engine_version, extract_pdf


@pytest.mark.parametrize(
    "stdout,stderr,expected",
    [
        ("", "", "tesseract-cli-unknown"),
        ("   ", "tesseract 5.5.0\n", "tesseract 5.5.0"),
        ("\ntesseract 5.4.1\n", "", "tesseract 5.4.1"),
    ],
)
def test_empty_and_whitespace_engine_version(monkeypatch, stdout, stderr, expected):
    monkeypatch.setattr("pdf2audiobook.pdf.shutil.which", lambda _: "/bin/tesseract")
    monkeypatch.setattr(
        "pdf2audiobook.pdf.subprocess.run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=stdout, stderr=stderr),
    )
    _ocr_engine_version.cache_clear()
    try:
        assert _ocr_engine_version() == expected
    finally:
        _ocr_engine_version.cache_clear()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda line: {**line, "bbox": [30, 40, 10, 50]},
        lambda line: {**line, "bbox": [10, True, 30, 50]},
        lambda line: {**line, "size": -2},
        lambda line: {**line, "size": float("nan")},
        lambda line: {**line, "text": "x" * 1_000_001},
    ],
)
def test_invalid_ocr_cache_lines_trigger_recognition(monkeypatch, tmp_path: Path, mutate):
    source = tmp_path / "scan.pdf"
    document = fitz.open()
    document.new_page()
    document.save(source)
    document.close()
    calls = []

    def fake_ocr(page, settings):
        calls.append(page.number)
        return [
            {"text": "Valid recognized text.", "bbox": [10, 20, 30, 40],
             "size": 12.0, "font": "OCR"},
        ]

    monkeypatch.setattr("pdf2audiobook.pdf._ocr_page_lines", fake_ocr)
    cache_dir = tmp_path / "ocr"
    extract_pdf(source, Pdf(ocr="always"), ocr_cache_dir=cache_dir)
    entry, = list(cache_dir.glob("*.json"))
    import json
    data = json.loads(entry.read_text())
    data["lines"][0] = mutate(data["lines"][0])
    entry.write_text(json.dumps(data, allow_nan=True))
    result = extract_pdf(source, Pdf(ocr="always"), ocr_cache_dir=cache_dir)
    assert len(calls) == 2
    assert result.spans[0].text == "Valid recognized text."
