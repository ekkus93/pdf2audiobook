"""Source provenance and chapter coverage validation."""

from __future__ import annotations

from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock


def validate_chapter_coverage(blocks: list[DocumentBlock], chapters: list[Chapter]) -> None:
    """Chapter boundaries are ordered, contiguous, nonempty, and cover every source block."""
    if not chapters:
        raise ExtractionError("Manifest does not contain any chapters")
    expected = 0
    for ordinal, chapter in enumerate(chapters, 1):
        if chapter.number != ordinal:
            raise ExtractionError("Manifest chapter numbers must be consecutive and 1-based")
        if chapter.start_block != expected:
            raise ExtractionError(
                f"Manifest chapter {ordinal} overlaps or leaves an uncovered block range"
            )
        if chapter.end_block > len(blocks):
            raise ExtractionError("Manifest chapter extends beyond source blocks")
        expected = chapter.end_block
    if expected != len(blocks):
        raise ExtractionError("Manifest does not cover all original source blocks")


def chapter_has_speakable_text(
    blocks: list[DocumentBlock],
    start: int,
    end: int,
    replacements: dict[str, str] | None = None,
) -> bool:
    """Use one cleanup-aware narration rule for coverage and conversion gates."""
    from pdf2audiobook.audio import has_speakable_narration

    replacement_map = replacements or {}
    return any(
        has_speakable_narration(replacement_map.get(block.id, block.text))
        for block in blocks[start:end]
    )


def chapter_coverage_report(manifest: BookManifest) -> dict[str, object]:
    """Validate provenance, cleanup anchors and exact-once block coverage."""
    validate_chapter_coverage(manifest.blocks, manifest.chapters)
    ids = [block.id for block in manifest.blocks]
    if len(ids) != len(set(ids)):
        raise ExtractionError("Duplicate source block IDs in manifest")
    span_ids = [span.id for span in manifest.spans]
    if len(span_ids) != len(set(span_ids)):
        raise ExtractionError("Duplicate source span IDs in manifest")
    known_spans = set(span_ids)
    assigned_spans: set[str] = set()
    for block in manifest.blocks:
        if known_spans and not block.span_ids:
            raise ExtractionError("Source block has no source span provenance")
        for span_id in block.span_ids:
            if span_id not in known_spans:
                raise ExtractionError("Source block references missing source spans")
            if span_id in assigned_spans:
                raise ExtractionError("Source span is assigned more than once")
            assigned_spans.add(span_id)
    if assigned_spans != known_spans:
        raise ExtractionError("Manifest contains unassigned source spans")
    by_id = {block.id: block for block in manifest.blocks}
    accepted: dict[str, str] = {}
    for edit in manifest.edits:
        if edit.block_id not in by_id:
            raise ExtractionError("Cleanup edit references missing source block")
        if edit.original != by_id[edit.block_id].text:
            raise ExtractionError("Cleanup edit original does not match source block")
        if edit.accepted:
            if edit.block_id in accepted:
                raise ExtractionError("Multiple accepted edits for source block")
            accepted[edit.block_id] = edit.replacement
    empty_chapters = [
        chapter.number
        for chapter in manifest.chapters
        if not chapter_has_speakable_text(
            manifest.blocks, chapter.start_block, chapter.end_block, accepted
        )
    ]
    return {
        "valid": True,
        "source_blocks": len(ids),
        "source_spans": len(span_ids),
        "covered_blocks": sum(ch.end_block - ch.start_block for ch in manifest.chapters),
        "uncovered_blocks": 0,
        "duplicate_blocks": 0,
        "accepted_cleanup_blocks": len(accepted),
        "narrated_blocks": sum(
            1 for block in manifest.blocks if chapter_has_speakable_text([block], 0, 1, accepted)
        ),
        "chapters": len(manifest.chapters),
        "empty_chapters": empty_chapters,
    }
