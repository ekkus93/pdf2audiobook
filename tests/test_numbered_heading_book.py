"""A book of large numbered or Roman chapter headings keeps its chapters end to end (R46)."""

import pymupdf
import pytest

from pdf2audiobook.config import Chapters, Pdf
from pdf2audiobook.document.structure import propose_chapters
from pdf2audiobook.pdf import extract_pdf


@pytest.mark.parametrize(
    "titles",
    [
        ["1. The Storm", "2. The Calm", "3. The Return"],
        ["I. THE STORM", "II. THE CALM", "III. THE RETURN"],
    ],
)
def test_extracted_pdf_with_display_headings_yields_each_chapter(tmp_path, titles):
    source = tmp_path / "book.pdf"
    with pymupdf.open() as document:
        for title in titles:
            page = document.new_page()
            page.insert_text((72, 100), title, fontsize=22)
            for row in range(6):
                page.insert_text(
                    (72, 150 + row * 16),
                    f"The chapter continues with ordinary readable body prose, line {row}.",
                    fontsize=11,
                )
        document.save(source)
    extracted = extract_pdf(source, Pdf(ocr="never"))
    chapters, _ = propose_chapters(extracted.blocks, set(), [], Chapters())
    assert [chapter.title for chapter in chapters] == titles
