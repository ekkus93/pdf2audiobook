"""The hand-edit merge: keeping a book's manual chapter edits across a fresh analysis."""

from __future__ import annotations

from dataclasses import dataclass, field

from pdf2audiobook.analysis.state import _AnalysisRun
from pdf2audiobook.analysis_state import (
    _hand_edit_conflict,
    _match_edited_chapter,
)
from pdf2audiobook.document.structure import (
    validate_chapter_coverage,
)
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.models import (
    BookManifest,
    Chapter,
    generated_baseline_fingerprint,
)
from pdf2audiobook.pdf import ExtractedDocument


@dataclass
class _HandEditMerge:
    """State for carrying hand edits from the old manifest onto new chapters.

    `matches` maps an old chapter id to its new chapter. `field_changes` holds
    the queued field values per new chapter id; `changed_chapter_numbers`
    names the chapters any conflict message must cite.
    """

    existing_manifest: BookManifest
    new_positions: dict[str, int]
    new_block_count: int
    old_chapters: list[Chapter]
    edited_by_id: dict[str, Chapter]
    matches: dict[str, Chapter]
    changed_chapter_numbers: set[int]
    field_changes: dict[str, dict[str, int | str | None]] = field(default_factory=dict)
    explicit_boundary_fields: dict[str, set[str]] = field(default_factory=dict)
    moved_neighbor_fields: dict[str, set[str]] = field(default_factory=dict)


def _match_old_chapters(
    old_chapters: list[Chapter],
    chapters: list[Chapter],
    existing_manifest: BookManifest,
    new_positions: dict[str, int],
    edited_by_id: dict[str, Chapter],
) -> dict[str, Chapter]:
    """Match each old chapter to at most one new chapter.

    An edited chapter with no match, or one sharing its match with another
    chapter, is a conflict; an unedited one is skipped.
    """
    matches: dict[str, Chapter] = {}
    claimed_matches: dict[str, Chapter] = {}
    for old in old_chapters:
        match = _match_edited_chapter(old, chapters, existing_manifest, new_positions)
        if match is None:
            if old.id in edited_by_id:
                raise _hand_edit_conflict(
                    f"Chapter {old.number} was edited but cannot be aligned",
                    {old.number},
                )
            continue
        owner = claimed_matches.get(match.id)
        if owner is not None:
            if old.id in edited_by_id or owner.id in edited_by_id:
                if old.id in edited_by_id and owner.id not in edited_by_id:
                    message = f"Chapter {old.number} was edited but cannot be aligned"
                    numbers = {old.number}
                elif owner.id in edited_by_id and old.id not in edited_by_id:
                    message = f"Chapter {owner.number} was edited but cannot be aligned"
                    numbers = {owner.number}
                else:
                    message = "Edited chapters cannot be uniquely matched"
                    numbers = {old.number, owner.number}
                raise _hand_edit_conflict(
                    message,
                    numbers,
                )
            continue
        matches[old.id] = match
        claimed_matches[match.id] = old
    return matches


def _queue_change(
    merge: _HandEditMerge,
    item: Chapter,
    field_name: str,
    value: int | str | None,
    chapter_number: int,
) -> None:
    """Queue one field value for a new chapter; a different second value conflicts."""
    current = merge.field_changes.setdefault(item.id, {}).get(field_name)
    if field_name in merge.field_changes[item.id] and current != value:
        raise _hand_edit_conflict(
            "Edited boundaries conflict",
            merge.changed_chapter_numbers | {chapter_number},
        )
    merge.field_changes[item.id][field_name] = value


def _map_boundary(merge: _HandEditMerge, position: int) -> int | None:
    """Map an old block position to the new one through its block id."""
    blocks = merge.existing_manifest.blocks
    if position == len(blocks):
        return merge.new_block_count
    if position < 0 or position >= len(blocks):
        return None
    return merge.new_positions.get(blocks[position].id)


def _queue_moved_boundary(
    merge: _HandEditMerge,
    edited: Chapter,
    match: Chapter,
    old_index: int,
    field_name: str,
) -> None:
    """Queue an edited start or end, and the matching edge of the old neighbour."""
    position = edited.start_block if field_name == "start_block" else edited.end_block
    mapped = _map_boundary(merge, position)
    if mapped is None:
        raise _hand_edit_conflict(
            f"Chapter {edited.number} boundary cannot be aligned",
            {edited.number},
        )
    _queue_change(merge, match, field_name, mapped, edited.number)
    merge.explicit_boundary_fields.setdefault(match.id, set()).add(field_name)
    neighbor_index = old_index - 1 if field_name == "start_block" else old_index + 1
    if not 0 <= neighbor_index < len(merge.old_chapters):
        return
    old_neighbor = merge.old_chapters[neighbor_index]
    neighbor = merge.matches.get(old_neighbor.id)
    if neighbor is None:
        raise _hand_edit_conflict(
            "Edited boundary neighbor cannot be aligned",
            {old_neighbor.number, edited.number},
        )
    neighbor_field = "end_block" if field_name == "start_block" else "start_block"
    _queue_change(merge, neighbor, neighbor_field, mapped, edited.number)
    merge.moved_neighbor_fields.setdefault(neighbor.id, set()).add(neighbor_field)
    merge.changed_chapter_numbers.add(old_neighbor.number)


def _queue_hand_edits(merge: _HandEditMerge) -> None:
    """Queue every edited title, voice and boundary onto its matched new chapter."""
    block_count = len(merge.existing_manifest.blocks)
    for old_index, edited in enumerate(merge.old_chapters):
        if edited.id not in merge.edited_by_id:
            continue
        if (
            edited.start_block >= block_count
            or edited.end_block > block_count
            or edited.start_block < 0
            or edited.end_block < 0
        ):
            raise _hand_edit_conflict(
                f"Chapter {edited.number} was edited but cannot be aligned",
                {edited.number},
            )
        match = merge.matches.get(edited.id)
        if match is None:
            raise _hand_edit_conflict(
                f"Chapter {edited.number} was edited but cannot be aligned",
                {edited.number},
            )
        title_edited = edited.generated_title is not None and edited.title != edited.generated_title
        start_edited = (
            edited.generated_start_block is not None
            and edited.start_block != edited.generated_start_block
        )
        end_edited = (
            edited.generated_end_block is not None
            and edited.end_block != edited.generated_end_block
        )
        voice_edited = edited.generated_voice_id != edited.voice_id
        if start_edited:
            _queue_moved_boundary(merge, edited, match, old_index, "start_block")
        if end_edited:
            _queue_moved_boundary(merge, edited, match, old_index, "end_block")
        if title_edited:
            _queue_change(merge, match, "title", edited.title, edited.number)
        if voice_edited:
            _queue_change(merge, match, "voice_id", edited.voice_id, edited.number)


def _apply_hand_edits(
    merge: _HandEditMerge, extracted: ExtractedDocument, chapters: list[Chapter]
) -> None:
    """Apply the queued fields, refusing empty chapters or broken coverage.

    A neighbour edge moved only to follow an edit becomes the new generated
    baseline, so it is not reported as a user edit.
    """
    for item in chapters:
        for field_name, value in merge.field_changes.get(item.id, {}).items():
            setattr(item, field_name, value)
        if item.end_block <= item.start_block:
            affected = sorted(merge.changed_chapter_numbers)
            if len(affected) == 2:
                message = (
                    f"Edited boundary between chapters {affected[0]} and {affected[1]} "
                    "cannot be aligned; approve or revert the named chapter(s)."
                )
                raise ExtractionError(message)
            raise _hand_edit_conflict("Edited chapter would be empty", set(affected))

    try:
        validate_chapter_coverage(extracted.blocks, chapters)
    except ExtractionError:
        raise _hand_edit_conflict(
            "Edited boundaries conflict",
            merge.changed_chapter_numbers,
        ) from None

    for item in chapters:
        fields = merge.moved_neighbor_fields.get(item.id, set()) - (
            merge.explicit_boundary_fields.get(item.id, set())
        )
        if "start_block" in fields:
            item.generated_start_block = item.start_block
        if "end_block" in fields:
            item.generated_end_block = item.end_block
        if fields:
            item.generated_fingerprint = generated_baseline_fingerprint(item)


def _merge_hand_edits(
    run: _AnalysisRun,
    extracted: ExtractedDocument,
    chapters: list[Chapter],
    warnings: list[str],
) -> None:
    """Carry hand-edited chapter fields from the old manifest onto new chapters."""
    existing_manifest = run.existing_manifest
    if not run.hand_edited_chapters or existing_manifest is None:
        return
    new_positions = {block.id: index for index, block in enumerate(extracted.blocks)}
    old_chapters = sorted(existing_manifest.chapters, key=lambda item: item.start_block)
    edited_by_id = {chapter.id: chapter for chapter in run.hand_edited_chapters}
    matches = _match_old_chapters(
        old_chapters, chapters, existing_manifest, new_positions, edited_by_id
    )
    merge = _HandEditMerge(
        existing_manifest=existing_manifest,
        new_positions=new_positions,
        new_block_count=len(extracted.blocks),
        old_chapters=old_chapters,
        edited_by_id=edited_by_id,
        matches=matches,
        changed_chapter_numbers={chapter.number for chapter in run.hand_edited_chapters},
    )
    _queue_hand_edits(merge)
    _apply_hand_edits(merge, extracted, chapters)
    preserved_numbers = sorted(matches[chapter.id].number for chapter in run.hand_edited_chapters)
    warnings.append(
        "Preserved user-edited chapter numbers: "
        + ", ".join(str(number) for number in preserved_numbers)
    )
