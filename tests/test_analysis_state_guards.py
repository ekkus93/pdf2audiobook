"""Analysis state: footnote setting changes, stage changes and chapter matching.

Test coverage round 2, U5. A footnote setting change on an approved workspace
must never override a cleanup decision the user already approved.
"""

from pathlib import Path

import fitz
import pytest

from pdf2audiobook.analysis import _match_old_chapters
from pdf2audiobook.analysis_state import (
    _changed_analysis_stages,
    _match_edited_chapter,
    _preserve_rejected_deterministic_edits,
)
from pdf2audiobook.config import Settings
from pdf2audiobook.document.narration import FOOTNOTE_OMIT_REASON
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.models import BookManifest, Chapter, CleanupEdit, DocumentBlock
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.review_ui import save_chapter_updates
from pdf2audiobook.workspace import read_manifest, write_manifest


def _approved_workspace(tmp_path: Path) -> tuple[Path, Path, Settings]:
    """Analyze a one-chapter PDF with one footnote, then approve it in review."""
    source = tmp_path / "notes.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((55, 100), "Chapter 1", fontsize=15)
    page.insert_text((55, 140), "A paragraph with a note reference.1", fontsize=12)
    page.insert_text((55, 180), "Another ordinary paragraph.", fontsize=12)
    page.insert_text((55, 745), "1 A separate footnote.", fontsize=7)
    doc.save(source)
    doc.close()
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.llm.enabled = False
    settings.pdf.ocr = "never"
    path = analyze_book(source, settings)
    manifest = read_manifest(path)
    save_chapter_updates(
        path,
        [
            {
                "id": chapter.id,
                "title": chapter.title,
                "start_block": chapter.start_block,
                "end_block": chapter.end_block,
            }
            for chapter in manifest.chapters
        ],
    )
    return source, path, settings


def _note(manifest: BookManifest) -> DocumentBlock:
    notes = [block for block in manifest.blocks if block.kind == "footnote"]
    assert len(notes) == 1
    return notes[0]


def test_omit_setting_refuses_to_override_an_approved_cleanup_edit(tmp_path):
    """U5.a: omitting a footnote the user already corrected and approved is refused."""
    source, path, settings = _approved_workspace(tmp_path)
    manifest = read_manifest(path)
    note = _note(manifest)
    manifest.edits.append(
        CleanupEdit(
            block_id=note.id,
            original=note.text,
            replacement=note.text.replace("separate", "corrected"),
            reason="reviewed by hand",
            confidence=1,
            accepted=True,
        )
    )
    write_manifest(path, manifest)
    before = path.read_bytes()
    settings.pdf.footnotes = "omit"

    with pytest.raises(ExtractionError) as error:
        analyze_book(source, settings)

    assert str(error.value) == (
        "Footnote policy conflicts with an approved cleanup edit; use a new output directory"
    )
    assert path.read_bytes() == before


def test_footnote_edits_the_old_setting_did_not_make_are_protected(tmp_path):
    """U5.a: policy-owned edits that don't match the recorded setting are not replaced."""
    source, path, settings = _approved_workspace(tmp_path)
    manifest = read_manifest(path)
    note = _note(manifest)
    # The workspace was made with "warn", which creates no omit edit; one is present.
    manifest.edits.append(
        CleanupEdit(
            block_id=note.id,
            original=note.text,
            replacement="",
            reason=FOOTNOTE_OMIT_REASON,
            confidence=0.9,
            accepted=False,
            provider="deterministic",
        )
    )
    write_manifest(path, manifest)
    before = path.read_bytes()
    settings.pdf.footnotes = "end"

    with pytest.raises(ExtractionError) as error:
        analyze_book(source, settings)

    assert str(error.value) == (
        "Footnote policy conflicts with protected cleanup decisions; use a new output directory"
    )
    assert path.read_bytes() == before


def test_switching_to_end_reports_how_many_footnotes_moved(tmp_path):
    """U5.b: the end setting records how many notes now follow their chapter."""
    source, path, settings = _approved_workspace(tmp_path)
    settings.pdf.footnotes = "end"

    assert analyze_book(source, settings) == path

    warnings = read_manifest(path).warnings
    assert (
        "Narrating 1 classified footnote(s) at the end of their chapter; "
        "source blocks are unchanged"
    ) in warnings
    assert not any(w.startswith("Narrating ") and "anchor" in w for w in warnings)
    text = (path.parent / "chapters" / "001.txt").read_text(encoding="utf-8")
    assert text.rstrip().endswith("A separate footnote.")


_CURRENT = {"extraction": "e" * 64, "chapter-boundaries": "c" * 64}


@pytest.mark.parametrize(
    ("report", "expected"),
    [
        (None, ["analysis"]),
        (b"{not json", ["analysis"]),
        (b"[]", ["analysis"]),
        (b'{"stages": ["extraction"]}', ["analysis"]),
        (
            b'{"stages": {"extraction": "' + b"e" * 64 + b'", "chapter-boundaries": 7}}',
            ["chapter-boundaries"],
        ),
        (b'{"stages": {"extraction": "' + b"x" * 64 + b'"}}', ["chapter-boundaries", "extraction"]),
        (
            b'{"stages": {"extraction": "'
            + b"e" * 64
            + b'", "chapter-boundaries": "'
            + b"c" * 64
            + b'"}}',
            ["analysis"],
        ),
    ],
    ids=[
        "missing",
        "not-json",
        "not-an-object",
        "stages-not-a-mapping",
        "stage-not-a-string",
        "changed-and-missing",
        "unchanged",
    ],
)
def test_changed_stages_fall_back_to_the_whole_analysis(tmp_path, report, expected):
    """U5.c: only a readable report narrows the change to named stages."""
    if report is not None:
        (tmp_path / "reports").mkdir()
        (tmp_path / "reports" / "analysis_fingerprints.json").write_bytes(report)

    assert _changed_analysis_stages(tmp_path, _CURRENT) == expected


def _previous_with_rejected_edit(block_id: str) -> BookManifest:
    return BookManifest(
        schema_version=3,
        input_sha256="x",
        title="Book",
        source_path="book.pdf",
        blocks=[
            DocumentBlock(id="a", page_index=0, text="One."),
            DocumentBlock(id="b", page_index=1, text="Two."),
        ],
        chapters=[
            Chapter(id="c1", number=1, title="One", start_block=0, end_block=1, confidence=1),
            Chapter(id="c2", number=2, title="Two", start_block=1, end_block=2, confidence=1),
        ],
        edits=[
            CleanupEdit(
                block_id=block_id,
                original="Two.",
                replacement="",
                reason="running header",
                confidence=0.9,
                accepted=False,
                provider="deterministic",
            )
        ],
    )


@pytest.mark.parametrize(("block_id", "number"), [("b", 2), ("gone", 1)])
def test_rejected_edit_that_cannot_be_aligned_names_its_chapter(block_id, number):
    """U5.c: a rejected edit that analysis no longer makes stops reanalysis; an edit
    whose block no longer exists is attributed to chapter 1."""
    with pytest.raises(ExtractionError) as error:
        _preserve_rejected_deterministic_edits(_previous_with_rejected_edit(block_id), [])

    assert str(error.value) == (
        f"Rejected cleanup edit for chapter {number} cannot be aligned; "
        "review the chapter before reanalysis"
    )


def _edited(start):
    return Chapter(
        id="old",
        number=2,
        title="Two",
        start_block=1,
        end_block=2,
        confidence=1,
        generated_start_block=start,
    )


@pytest.mark.parametrize("start", [None, 2, 99], ids=["no-start", "at-end", "past-end"])
def test_edited_chapter_without_a_usable_generated_start_is_a_conflict(start):
    """U5.d: an edited chapter that can't be located is a hand-edit conflict."""
    previous = _previous_with_rejected_edit("b")
    new = [
        Chapter(id="n1", number=1, title="One", start_block=0, end_block=2, confidence=1),
    ]
    old = _edited(start)
    positions = {"a": 0, "b": 1}

    assert _match_edited_chapter(old, new, previous, positions) is None
    with pytest.raises(ExtractionError) as error:
        _match_old_chapters([old], new, previous, positions, {"old": old})

    assert str(error.value) == (
        "Chapter 2 was edited but cannot be aligned for chapter(s) 2; "
        "approve or revert the named chapter(s)."
    )
    # An unedited chapter that can't be located is simply not carried over.
    assert _match_old_chapters([old], new, previous, positions, {}) == {}


def test_edited_chapter_with_a_valid_generated_start_matches(tmp_path):
    """U5.d control: the last valid block index still matches its chapter."""
    previous = _previous_with_rejected_edit("b")
    new = [
        Chapter(id="n1", number=1, title="One", start_block=0, end_block=1, confidence=1),
        Chapter(id="n2", number=2, title="Two", start_block=1, end_block=2, confidence=1),
    ]

    assert _match_edited_chapter(_edited(1), new, previous, {"a": 0, "b": 1}).id == "n2"
