"""Fail-closed running-header checks for prose and quotation fragments."""
from __future__ import annotations

from pathlib import Path

import fitz

from pdf2audiobook.config import Pdf
from pdf2audiobook.document.structure import pagination_cleanup
from pdf2audiobook.pdf import extract_pdf


def test_body_phrase_prevents_identical_running_header_deletion(tmp_path: Path):
    source = tmp_path / "quoted-prose.pdf"
    doc = fitz.open()
    for index in range(4):
        page = doc.new_page(width=595, height=842)
        page.insert_text((60, 38), "Remember me", fontsize=10)
        page.insert_text(
            (60, 180),
            "Remember me" if index == 3 else f"Chapter prose page {index}",
            fontsize=11,
        )
    doc.save(source)
    doc.close()
    extracted = extract_pdf(source, Pdf(ocr="never"))
    edits = pagination_cleanup(extracted.blocks, extracted.page_sizes, Pdf())
    assert not any(edit.original == "Remember me" for edit in edits)


def test_short_quoted_and_unfinished_margin_dialogue_is_preserved(tmp_path: Path):
    source = tmp_path / "margin-dialogue.pdf"
    doc = fitz.open()
    for index in range(3):
        page = doc.new_page(width=595, height=842)
        page.insert_text((55, 35), "Yes,", fontsize=10)
        page.insert_text((55, 70), "He replied”", fontsize=10)
        page.insert_text((55, 180), f"Unique body content {index}", fontsize=11)
    doc.save(source)
    doc.close()
    extracted = extract_pdf(source, Pdf(ocr="never"))
    edits = pagination_cleanup(extracted.blocks, extracted.page_sizes, Pdf())
    assert not any(edit.original in {"Yes,", "He replied”"} for edit in edits)


def test_footer_contiguous_with_body_is_not_running_footer(tmp_path: Path):
    source = tmp_path / "footer-dialogue.pdf"
    doc = fitz.open()
    for index in range(3):
        page = doc.new_page(width=595, height=842)
        page.insert_text((55, 740), f"Dialogue from page {index}.", fontsize=11)
        page.insert_text((55, 760), "And so it ends", fontsize=11)
    doc.save(source)
    doc.close()
    extracted = extract_pdf(source, Pdf(ocr="never"))
    edits = pagination_cleanup(extracted.blocks, extracted.page_sizes, Pdf())
    assert not any(edit.original == "And so it ends" for edit in edits)
