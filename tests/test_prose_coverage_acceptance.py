"""No-loss and no-duplication acceptance for source-aligned chapter transcripts."""

import pytest

from pdf2audiobook.document.structure import chapter_coverage_report, render_chapter_texts
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.models import BookManifest, Chapter, CleanupEdit, DocumentBlock, SourceSpan


def book():
    text = [
        "TOKEN_ALPHA beginning.",
        "TOKEN_BRAVO body.",
        "TOKEN_CHARLIE midpoint.",
        "TOKEN_DELTA ending.",
        "42",
    ]
    blocks = [
        DocumentBlock(
            id=f"block-{i}",
            span_ids=[f"span-{i}"],
            page_index=0 if i < 3 else 1,
            text=value,
            order=i,
        )
        for i, value in enumerate(text)
    ]
    spans = [
        SourceSpan(id=f"span-{i}", page_index=block.page_index, text=block.text)
        for i, block in enumerate(blocks)
    ]
    chapters = [
        Chapter(id="c1", number=1, title="First", start_block=0, end_block=2, confidence=0.99),
        Chapter(id="c2", number=2, title="Second", start_block=2, end_block=5, confidence=0.99),
    ]
    return BookManifest(
        schema_version=2,
        input_sha256="1" * 64,
        title="Synthetic",
        source_path="synthetic.pdf",
        blocks=blocks,
        spans=spans,
        chapters=chapters,
    )


def test_midpage_chapters_preserve_all_prose_exactly_once(tmp_path):
    manifest = book()
    assert manifest.blocks[1].page_index == manifest.blocks[2].page_index
    report = chapter_coverage_report(manifest)
    assert report["uncovered_blocks"] == 0
    assert report["duplicate_blocks"] == 0
    assert report["narrated_blocks"] == len(manifest.blocks)
    render_chapter_texts(manifest, tmp_path)
    data = [(tmp_path / "chapters" / f"{i:03d}.txt").read_text(encoding="utf-8") for i in (1, 2)]
    for token in ("TOKEN_ALPHA", "TOKEN_BRAVO", "TOKEN_CHARLIE", "TOKEN_DELTA"):
        assert sum(chapter.count(token) for chapter in data) == 1


def test_exclusion_requires_exact_source_matched_audit(tmp_path):
    manifest = book()
    manifest.edits.append(
        CleanupEdit(
            block_id="block-4",
            original="42",
            replacement="",
            reason="user-approved folio",
            confidence=1,
            accepted=True,
        )
    )
    report = chapter_coverage_report(manifest)
    assert report["accepted_cleanup_blocks"] == 1
    assert report["narrated_blocks"] == 4
    render_chapter_texts(manifest, tmp_path)
    output = (tmp_path / "chapters" / "002.txt").read_text()
    assert "TOKEN_CHARLIE" in output and "TOKEN_DELTA" in output
    assert "42" not in output


@pytest.mark.parametrize("kind", ["hole", "overlap", "uncovered"])
def test_invalid_chapter_spans_fail_closed(kind):
    manifest = book()
    if kind == "hole":
        manifest.chapters[1].start_block = 3
    elif kind == "overlap":
        manifest.chapters[1].start_block = 1
    else:
        manifest.chapters[1].end_block = 4
    with pytest.raises(ExtractionError):
        chapter_coverage_report(manifest)


def test_duplicate_block_and_invalid_cleanup_anchors_fail_closed():
    manifest = book()
    manifest.blocks[1].id = manifest.blocks[0].id
    with pytest.raises(ExtractionError, match="Duplicate source block IDs"):
        chapter_coverage_report(manifest)

    manifest = book()
    manifest.edits.append(
        CleanupEdit(
            block_id="block-0",
            original="wrong",
            replacement="",
            reason="invalid",
            confidence=1,
            accepted=True,
        )
    )
    with pytest.raises(ExtractionError, match="original does not match"):
        chapter_coverage_report(manifest)
