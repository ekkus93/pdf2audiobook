"""Display-equation review classification preserves exact source and narration breaks."""

from pathlib import Path

import fitz

from pdf2audiobook.config import LLM, Chapters, General, Pdf, Settings
from pdf2audiobook.pdf import extract_pdf
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.special_material import equation_line_indices


def test_short_formulas_not_inline_prose_or_captions():
    lines = [
        {"text": "E = mc^2"},
        {"text": "f(x) = x^2 + 1"},
        {"text": "x² + y² = z²"},
        {"text": "The result = 4 in this experiment."},
        {"text": "Figure 1: E = mc^2"},
        {"text": "1. A numbered list item."},
        {"text": "The symbol ∑ appears in this sentence."},
        {"text": "A URL is https://example.invalid/a=b"},
    ]
    selected, warnings = equation_line_indices(lines, page_number=3)
    assert selected == {0, 1, 2}
    assert "Page 3" in warnings[0]
    assert "preserved" in warnings[0]


def test_pdf_equation_is_typed_and_kept_separate_for_narration(tmp_path: Path):
    source = tmp_path / "math.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((55, 100), "Chapter 1", fontsize=16)
    page.insert_text((55, 145), "The relationship follows from conservation.", fontsize=12)
    page.insert_text((55, 160), "E = mc^2", fontsize=12)
    page.insert_text((55, 175), "This is the next sentence.", fontsize=12)
    document.save(source)
    document.close()

    extracted = extract_pdf(source, Pdf(ocr="never"))
    equations = [block for block in extracted.blocks if block.kind == "equation"]
    assert len(equations) == 1
    assert equations[0].text == "E = mc^2"
    assert any(span.id == equations[0].id and span.text == equations[0].text
               for span in extracted.spans)
    assert any("displayed equation" in warning for warning in extracted.warnings)
    assert not any(block.kind == "equation" and "relationship" in block.text
                   for block in extracted.blocks)

    settings = Settings(
        general=General(output_dir=str(tmp_path / "output")),
        pdf=Pdf(ocr="never"),
        llm=LLM(enabled=False),
        chapters=Chapters(allow_single_chapter=True),
    )
    manifest_path = analyze_book(source, settings)
    spoken = (manifest_path.parent / "chapters" / "001.txt").read_text()
    assert "E = mc^2" in spoken
    assert "\n\nE = mc^2\n\n" in spoken
    assert "This is the next sentence." in spoken
