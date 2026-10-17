"""Edge cases for conservative, lossless displayed-equation review flags."""

from pathlib import Path

import fitz

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import extract_pdf
from pdf2audiobook.special_material import equation_line_indices


def test_equations_require_symbolic_evidence_not_body_prose():
    raw = [
        "x = 4",
        "f(x) = x + 1",
        "∑ i = n",
        "The parameter x = 4 appears in the chapter.",
        "Figure 3: x = 4",
        "Table 2: x = 4",
        "Chapter 4: x = 4",
        "1. Read x = 4 as an example.",
        "The text includes an ∑ symbol but is prose.",
        "Visit https://example.invalid/?x=4 for examples",
        "The measurement is 4.",
        "",
    ]
    flags, warnings = equation_line_indices([{"text": text} for text in raw], page_number=7)
    assert flags == {0, 1, 2}
    assert len(warnings) == 1
    assert "Page 7" in warnings[0]
    assert "preserved" in warnings[0]


def test_equation_review_ignores_nontext_and_oversized_lines():
    flags, warnings = equation_line_indices(
        [
            {"text": None},
            {"text": 42},
            {"text": "x = " + "z" * 145},
            {"text": "The letter x denotes the constant. " * 12},
        ],
        page_number=1,
    )
    assert flags == set()
    assert warnings == []


def test_pdf_equation_review_preserves_line_text_and_span_order(tmp_path: Path):
    source = tmp_path / "displayed-formula.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    texts = [
        "Chapter 1",
        "Ordinary opening prose.",
        "f(x) = x + 1",
        "Ordinary closing prose.",
    ]
    for i, text in enumerate(texts):
        page.insert_text((72, 95 + i * 42), text, fontsize=14)
    doc.save(source)
    doc.close()

    extracted = extract_pdf(source, Pdf(ocr="never"))
    blocks = extracted.blocks
    assert [b.text for b in blocks] == texts
    assert [b.kind for b in blocks].count("equation") == 1
    assert blocks[2].kind == "equation"
    assert len(extracted.spans) == len(blocks)
    assert [(b.id, b.text) for b in blocks] == [(span.id, span.text) for span in extracted.spans]
    assert any("displayed equation" in w for w in extracted.warnings)
