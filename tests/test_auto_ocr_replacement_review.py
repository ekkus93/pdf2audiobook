"""Review automatic OCR that omits short selectable source text.

Uses a synthetic PDF and deterministic recognition stubs; no downloads.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import extract_pdf


@pytest.mark.parametrize(
    ("mode", "recognized_text", "should_warn"),
    [
        ("auto", "Scanned content completely unrelated to the chapter.", True),
        ("auto", "Chapter 7 scanned content from this page.", False),
        ("always", "Scanned content completely unrelated to the chapter.", False),
    ],
)
def test_auto_ocr_flags_missing_selectable_headings_without_mixing_layers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
    recognized_text: str,
    should_warn: bool,
) -> None:
    source = tmp_path / "short-heading.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=300)
        page.insert_text((45, 70), "Chapter 7", fontsize=16)
        doc.save(source)

    def recognized(*args, **kwargs):
        return [{
            "text": recognized_text,
            "bbox": [45, 60, 350, 76],
            "font": "OCR",
            "size": 16.0,
        }]

    monkeypatch.setattr("pdf2audiobook.pdf._cached_ocr_lines", recognized)
    extracted = extract_pdf(source, Pdf(ocr=mode))
    assert len(extracted.spans) == len(extracted.blocks) == 1
    assert extracted.spans[0].text == recognized_text
    assert extracted.spans[0].origin == "ocr"
    flagged = any(
        "automatic OCR did not reproduce short selectable text" in warning
        for warning in extracted.warnings
    )
    assert flagged is should_warn
    assert all("Chapter 7" not in block.text for block in extracted.blocks if should_warn)


def test_auto_ocr_on_image_only_page_does_not_claim_missing_selectable_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    source = tmp_path / "blank.pdf"
    with fitz.open() as doc:
        doc.new_page(width=400, height=300)
        doc.save(source)
    monkeypatch.setattr(
        "pdf2audiobook.pdf._cached_ocr_lines",
        lambda *args, **kwargs: [{
            "text": "A scanned line without a selectable counterpart.",
            "bbox": [45, 60, 355, 76],
            "font": "OCR",
            "size": 16.0,
        }],
    )
    extracted = extract_pdf(source, Pdf(ocr="auto"))
    assert len(extracted.spans) == 1
    assert extracted.spans[0].origin == "ocr"
    assert not any(
        "automatic OCR did not reproduce short selectable text" in warning
        for warning in extracted.warnings
    )
