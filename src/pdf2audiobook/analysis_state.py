"""Preserve reviewed analysis and reconcile footnote policy changes."""

from __future__ import annotations

from pathlib import Path

from pdf2audiobook.document.structure import (
    footnote_anchor_edits,
    footnote_omit_edits,
    place_footnotes,
)
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.jsonio import load_bounded_json
from pdf2audiobook.models import BookManifest, Chapter, CleanupEdit


def _preserve_rejected_deterministic_edits(
    previous: BookManifest | None, edits: list[CleanupEdit]
) -> None:
    """Carry a rejected deterministic edit forward by block identity and reason."""
    if previous is None:
        return
    rejected = [
        edit for edit in previous.edits if edit.provider == "deterministic" and not edit.accepted
    ]
    regenerated = {
        (edit.block_id, edit.reason, edit.original, edit.replacement): edit for edit in edits
    }
    for edit in rejected:
        key = (edit.block_id, edit.reason, edit.original, edit.replacement)
        replacement = regenerated.get(key)
        if replacement is None:
            old_position = next(
                (index for index, block in enumerate(previous.blocks) if block.id == edit.block_id),
                None,
            )
            chapter_number = 1
            if old_position is not None:
                chapter_number = next(
                    (
                        chapter.number
                        for chapter in previous.chapters
                        if chapter.start_block <= old_position < chapter.end_block
                    ),
                    1,
                )
            raise ExtractionError(
                f"Rejected cleanup edit for chapter {chapter_number} cannot be aligned; "
                "review the chapter before reanalysis"
            )
        replacement.accepted = edit.accepted


def _changed_analysis_stages(folder: Path, current: dict[str, str]) -> list[str]:
    """Return changed stage names without loading or displaying their inputs."""
    previous = load_bounded_json(
        folder / "reports" / "analysis_fingerprints.json", max_bytes=4096, max_depth=8
    )
    prior_stages = previous.get("stages") if isinstance(previous, dict) else None
    if not isinstance(prior_stages, dict):
        return ["analysis"]
    changed = sorted(
        name
        for name, value in current.items()
        if not isinstance(prior_stages.get(name), str) or prior_stages[name] != value
    )
    return changed or ["analysis"]


def _change_footnote_policy(manifest: BookManifest, previous: str, current: str) -> BookManifest:
    """Rebuild policy-owned edits while preserving unrelated approved decisions."""

    def policy_edit(edit: CleanupEdit) -> bool:
        return edit.provider == "deterministic" and (
            edit.reason == "explicit footnotes=omit policy (conservative classification)"
            or (
                edit.reason.startswith("footnote anchor marker ")
                and edit.reason.endswith(" (note handled)")
            )
        )

    other = [edit for edit in manifest.edits if not policy_edit(edit)]

    def generated(policy: str) -> list[CleanupEdit]:
        notes = [block for block in manifest.blocks if block.kind == "footnote"]
        owned = footnote_omit_edits(manifest.blocks) if policy == "omit" else []
        accepted = {edit.block_id for edit in other if edit.accepted}
        if any(edit.block_id in accepted for edit in owned):
            raise ExtractionError(
                "Footnote policy conflicts with an approved cleanup edit; use a new output directory"
            )
        if notes and policy in {"inline", "end", "omit"}:
            owned.extend(
                footnote_anchor_edits(manifest.blocks, accepted | {e.block_id for e in owned})
            )
        return owned

    original = [edit.model_dump(mode="json") for edit in manifest.edits if policy_edit(edit)]
    expected = [edit.model_dump(mode="json") for edit in generated(previous)]
    if original != expected:
        raise ExtractionError(
            "Footnote policy conflicts with protected cleanup decisions; use a new output directory"
        )
    updated = manifest.model_copy(deep=True)
    updated.edits = [*other, *generated(current)]
    updated.warnings = [
        warning
        for warning in updated.warnings
        if not (warning.startswith("Excluded ") and "footnote" in warning)
        and not (warning.startswith("Narrating ") and "footnote" in warning)
    ]
    notes = [block for block in updated.blocks if block.kind == "footnote"]
    if notes and current == "omit":
        updated.warnings.append(
            f"Excluded {len(notes)} conservatively classified footnote "
            "block(s) under explicit omit policy; inspect audited cleanup edits"
        )
    if notes and current in {"inline", "end"}:
        moved = kept = 0
        for chapter in updated.chapters:
            _, moved_count, kept_count = place_footnotes(
                updated.blocks[chapter.start_block : chapter.end_block], current
            )
            moved += moved_count
            kept += kept_count
        if current == "end":
            updated.warnings.append(
                f"Narrating {moved} classified footnote(s) at the end of their chapter; "
                "source blocks are unchanged"
            )
        else:
            updated.warnings.append(
                f"Narrating {moved} classified footnote(s) after the paragraph holding "
                f"their anchor; {kept} without a unique anchor keep their PDF position"
            )
    return updated


def _match_edited_chapter(
    edited: Chapter,
    chapters: list[Chapter],
    previous: BookManifest,
    new_positions: dict[str, int],
) -> Chapter | None:
    """Find the regenerated chapter that an edited chapter was generated as.

    Chapter numbers shift whenever analysis finds more or fewer chapters, so the
    analysis-generated start block (mapped through stable block IDs) identifies
    the chapter, never its number. The generated title breaks a tie.
    """
    generated_start = edited.generated_start_block
    if generated_start is None or generated_start >= len(previous.blocks):
        return None
    old_start = new_positions.get(previous.blocks[generated_start].id)
    if old_start is None:
        return None
    exact = [
        chapter
        for chapter in chapters
        if (
            chapter.generated_start_block
            if chapter.generated_start_block is not None
            else chapter.start_block
        )
        == old_start
    ]
    if len(exact) == 1:
        return exact[0]
    containing = [
        chapter
        for chapter in chapters
        if (
            chapter.generated_start_block
            if chapter.generated_start_block is not None
            else chapter.start_block
        )
        <= old_start
        and (
            chapter.generated_end_block
            if chapter.generated_end_block is not None
            else chapter.end_block
        )
        > old_start
    ]
    return containing[0] if len(containing) == 1 else None


def _hand_edit_conflict(message: str, numbers: set[int]) -> ExtractionError:
    chapter_numbers = ", ".join(str(number) for number in sorted(numbers))
    return ExtractionError(
        f"{message} for chapter(s) {chapter_numbers}; approve or revert the named chapter(s)."
    )
