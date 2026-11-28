"""Text inside figures and tables can be left out of narration, visibly and reversibly (F.08).

Modelled on a figure-heavy research paper: diagram labels and table cells were read aloud as
they appear. Extraction classifies them `figure_text`; `pdf.figure_text = "omit"` turns them
into accepted empty cleanup edits like omitted footnotes. Prose in a drawn box, headings
beside a figure, and captions stay narrated.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pdf2audiobook.config import Pdf, Settings
from pdf2audiobook.document.narration import FIGURE_TEXT_OMIT_REASON
from pdf2audiobook.pdf import extract_pdf
from pdf2audiobook.special_material import _CAPTION

BODY = "Ordinary body text of the paper continues here in normal sized type."
LONG = "This boxed abstract is real prose that a listener needs to hear in full."


def _page(doc: fitz.Document) -> fitz.Page:
    page = doc.new_page(width=612, height=792)
    for row in range(6):
        page.insert_text((72, 60 + 14 * row), BODY, fontsize=10)
    return page


def _figure(page: fitz.Page, top: float = 200) -> None:
    """A drawn diagram: a frame, two boxes and an arrow, with small labels inside."""
    page.draw_rect(fitz.Rect(100, top, 500, top + 160), color=(0, 0, 0))
    page.draw_rect(fitz.Rect(130, top + 40, 230, top + 90), color=(0, 0, 0))
    page.draw_rect(fitz.Rect(370, top + 40, 470, top + 90), color=(0, 0, 0))
    page.draw_line(fitz.Point(230, top + 65), fitz.Point(370, top + 65), color=(0, 0, 0))
    page.insert_text((150, top + 68), "Input", fontsize=7)
    page.insert_text((390, top + 68), "Output", fontsize=7)
    page.insert_text((250, top + 120), "Model step", fontsize=7)


def _extract(tmp_path: Path, build) -> list:
    source = tmp_path / "paper.pdf"
    doc = fitz.open()
    build(doc)
    doc.save(source)
    doc.close()
    return extract_pdf(source, Pdf(ocr="never")).blocks


def test_labels_inside_a_drawn_figure_are_figure_text(tmp_path: Path) -> None:
    def build(doc: fitz.Document) -> None:
        page = _page(doc)
        _figure(page)
        page.insert_text((100, 380), "Figure 1 A model rewriting its own weights.", fontsize=8)
        page.insert_text((72, 420), BODY, fontsize=10)

    blocks = _extract(tmp_path, build)
    kinds = {block.text: block.kind for block in blocks}
    assert kinds["Input"] == kinds["Output"] == kinds["Model step"] == "figure_text"
    assert kinds["Figure 1 A model rewriting its own weights."] == "caption"
    assert all(kind != "figure_text" for text, kind in kinds.items() if text == BODY)


def test_prose_in_a_drawn_box_is_not_figure_text(tmp_path: Path) -> None:
    def build(doc: fitz.Document) -> None:
        page = _page(doc)
        page.draw_rect(fitz.Rect(70, 200, 540, 300), color=(0, 0, 0))
        for row in range(5):
            page.insert_text((80, 220 + 15 * row), LONG, fontsize=10)

    blocks = _extract(tmp_path, build)
    assert not [block for block in blocks if block.kind == "figure_text"]


def test_a_heading_larger_than_the_body_inside_a_figure_area_is_kept(tmp_path: Path) -> None:
    def build(doc: fitz.Document) -> None:
        page = _page(doc)
        _figure(page)
        page.insert_text((150, 330), "Results", fontsize=14)

    kinds = {block.text: block.kind for block in _extract(tmp_path, build)}
    assert kinds["Input"] == "figure_text"
    assert kinds["Results"] != "figure_text"


def test_a_table_drawn_with_horizontal_rules_is_figure_text(tmp_path: Path) -> None:
    def build(doc: fitz.Document) -> None:
        page = _page(doc)
        page.insert_text((72, 200), "Table 2 Settings shared by all sessions.", fontsize=8)
        for y in (210, 232, 290):
            page.draw_line(fitz.Point(72, y), fitz.Point(540, y), color=(0, 0, 0), width=0.5)
        page.insert_text((80, 226), "Setting", fontsize=9)
        page.insert_text((300, 226), "Value", fontsize=9)
        page.insert_text((80, 250), "Seeds", fontsize=9)
        page.insert_text((300, 250), "five", fontsize=9)
        page.insert_text((72, 330), BODY, fontsize=10)

    kinds = {block.text: block.kind for block in _extract(tmp_path, build)}
    assert kinds["Seeds"] in {"figure_text", "table"}
    assert kinds["Setting"] in {"figure_text", "table"}
    assert kinds["Table 2 Settings shared by all sessions."] != "figure_text"


@pytest.mark.parametrize(
    ("line", "caption"),
    [
        ("Figure 3 A model reads its own weights.", True),
        ("Figure 3: A model reads its own weights.", True),
        ("Table 5 Settings shared by all sessions", True),
        ("Figure 3 shows the model reading its weights.", False),
        ("Table 5 lists the settings.", False),
        ("Fig. 1); the model", False),
    ],
)
def test_captions_without_punctuation_need_a_capitalised_word(line: str, caption: bool) -> None:
    assert (_CAPTION.match(line) is not None) is caption


def _analyze(tmp_path: Path, policy: str):
    from pdf2audiobook.pipeline import analyze_book
    from pdf2audiobook.workspace import read_manifest

    source = tmp_path / "paper.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 60), "1 Introduction", fontsize=16)
    for row in range(6):
        page.insert_text((72, 90 + 14 * row), BODY, fontsize=10)
    _figure(page, top=220)
    doc.save(source)
    doc.close()
    settings = Settings()
    settings.llm.enabled = False
    settings.pdf.ocr = "never"
    settings.pdf.figure_text = policy  # type: ignore[assignment]
    settings.chapters.allow_single_chapter = True
    settings.general.output_dir = tmp_path / "out"
    return read_manifest(analyze_book(source, settings))


def test_omit_leaves_figure_text_out_as_accepted_reversible_edits(tmp_path: Path) -> None:
    manifest = _analyze(tmp_path, "omit")
    edits = [edit for edit in manifest.edits if edit.reason == FIGURE_TEXT_OMIT_REASON]
    assert sorted(edit.original for edit in edits) == ["Input", "Model step", "Output"]
    assert all(edit.accepted and edit.replacement == "" for edit in edits)
    # The source text itself is kept; only narration leaves it out.
    assert {"Input", "Output"} <= {block.text for block in manifest.blocks}
    assert any("out of narration under pdf.figure_text = omit" in w for w in manifest.warnings)


def test_warn_narrates_figure_text_and_says_how_to_leave_it_out(tmp_path: Path) -> None:
    manifest = _analyze(tmp_path, "warn")
    assert not [edit for edit in manifest.edits if edit.reason == FIGURE_TEXT_OMIT_REASON]
    assert any("set pdf.figure_text = omit" in warning for warning in manifest.warnings)
