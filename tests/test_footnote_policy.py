"""Conservative typed footnotes and opt-in audited omission."""
from pathlib import Path

import fitz

from pdf2audiobook.config import LLM, Chapters, General, Pdf, Settings
from pdf2audiobook.pdf import extract_pdf
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.workspace import read_manifest


def _make_source(path: Path, *, near_body: bool = False) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((55, 100), "Chapter 1", fontsize=15)
    page.insert_text((55, 140), "A main paragraph with a note reference.", fontsize=12)
    page.insert_text((55, 180), "Another ordinary body paragraph.", fontsize=12)
    if near_body:
        page.insert_text((55, 695), "This is ordinary text near the bottom.", fontsize=12)
        page.insert_text((55, 711), "1 A list item near the body.", fontsize=7)
    else:
        page.insert_text((55, 745), "1 This is a separate footnote.", fontsize=7)
    doc.save(path)
    doc.close()


def test_typed_footnote_preserves_source_and_warn_policy(tmp_path: Path):
    source = tmp_path / "notes.pdf"
    _make_source(source)
    result = extract_pdf(source, Pdf(ocr="never", footnotes="warn"))
    notes = [block for block in result.blocks if block.kind == "footnote"]
    assert len(notes) == 1
    assert notes[0].text == "1 This is a separate footnote."
    assert any(span.id == notes[0].id and span.text == notes[0].text
               for span in result.spans)
    assert any("likely footnote anchor" in w for w in result.warnings)


def test_footnote_omit_requires_opt_in_and_is_audited(tmp_path: Path):
    source = tmp_path / "notes.pdf"
    _make_source(source)
    for policy in ("warn", "inline", "omit"):
        settings = Settings(
            general=General(output_dir=str(tmp_path / policy)),
            pdf=Pdf(ocr="never", footnotes=policy),
            llm=LLM(enabled=False),
            chapters=Chapters(allow_single_chapter=True),
        )
        manifest_path = analyze_book(source, settings)
        manifest = read_manifest(manifest_path)
        assert any("separate footnote" in b.text for b in manifest.blocks)
        text = (manifest_path.parent / "chapters" / "001.txt").read_text()
        omitted = [e for e in manifest.edits if e.accepted and "footnotes=omit" in e.reason]
        if policy == "omit":
            assert len(omitted) == 1
            assert omitted[0].original == "1 This is a separate footnote."
            assert omitted[0].replacement == ""
            assert "separate footnote" not in text
            assert any("Excluded 1" in w for w in manifest.warnings)
        else:
            assert not omitted
            assert "separate footnote" in text


def test_small_numbered_body_line_is_not_classified(tmp_path: Path):
    source = tmp_path / "list.pdf"
    _make_source(source, near_body=True)
    result = extract_pdf(source, Pdf(ocr="never"))
    assert not any(block.kind == "footnote" for block in result.blocks)
    assert any("A list item near the body" in block.text for block in result.blocks)
