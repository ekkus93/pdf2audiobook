"""Accept or reject pending cleanup and reading edits proposed during analysis.

An edit is a proposal until a person accepts it. Accepting one changes the narrated
text of its chapter, so it goes through the same planner and transaction as every other
chapter update: a hand-edited chapter file is a conflict and nothing is published.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pdf2audiobook.chapter_artifacts import resolve_footnote_policy
from pdf2audiobook.document.structure import render_chapter_texts
from pdf2audiobook.errors import ConfigError
from pdf2audiobook.models import BookManifest, CleanupEdit
from pdf2audiobook.workspace import read_manifest, workspace_lock, write_json, write_manifest

STATUSES = ("pending", "accepted", "rejected", "all")


@dataclass(frozen=True)
class EditRow:
    block_id: str
    chapter: int | None
    provider: str
    status: str
    reason: str
    original: str
    replacement: str


def edit_status(edit: CleanupEdit) -> str:
    """Built-in edits start accepted, so an unaccepted one was rejected during review."""
    if edit.accepted:
        return "accepted"
    return "rejected" if edit.provider == "deterministic" else "pending"


def _chapter_of(manifest: BookManifest, block_id: str) -> int | None:
    index = next((i for i, block in enumerate(manifest.blocks) if block.id == block_id), None)
    if index is None:
        return None
    for chapter in manifest.chapters:
        if chapter.start_block <= index < chapter.end_block:
            return chapter.number
    return None


def list_edits(manifest_path: Path, *, status: str = "pending") -> list[EditRow]:
    """Edits in manifest order; reading never locks or recovers."""
    if status not in STATUSES:
        raise ConfigError("Edit status must be pending, accepted, rejected or all")
    manifest = read_manifest(manifest_path)
    rows = [
        EditRow(
            edit.block_id,
            _chapter_of(manifest, edit.block_id),
            edit.provider,
            edit_status(edit),
            edit.reason,
            edit.original,
            edit.replacement,
        )
        for edit in manifest.edits
    ]
    return [row for row in rows if status == "all" or row.status == status]


def _select(
    manifest: BookManifest, block_ids: Sequence[str] | None, verb: str
) -> list[CleanupEdit]:
    """Pending edits to act on; refuse unknown or ambiguous block IDs before any change."""
    pending = [edit for edit in manifest.edits if edit_status(edit) == "pending"]
    if block_ids is None:
        return pending
    chosen: list[CleanupEdit] = []
    for block_id in dict.fromkeys(block_ids):
        matching = [edit for edit in manifest.edits if edit.block_id == block_id]
        if not matching:
            raise ConfigError("Unknown edit; run 'pdf2audiobook edits list' to see block IDs")
        open_ones = [edit for edit in matching if edit_status(edit) == "pending"]
        if not open_ones and any(edit_status(edit) == "rejected" for edit in matching):
            raise ConfigError(
                "That edit was rejected during review; it cannot be accepted or rejected here"
            )
        if len(open_ones) > 1:
            raise ConfigError(
                "More than one pending edit targets that block; reject the unwanted one first"
            )
        if not open_ones and verb == "reject":
            raise ConfigError("That edit is already accepted and cannot be rejected")
        chosen.extend(open_ones)
    return chosen


def _audit(folder: Path, action: str, edits: Sequence[CleanupEdit]) -> None:
    """Record who-did-what without book text; the audit never blocks the change."""
    if not edits:
        return
    path = folder / "reports" / "edit_decisions.json"
    try:
        from pdf2audiobook.jsonio import load_bounded_json

        previous = load_bounded_json(path, max_bytes=4 * 1024 * 1024, max_depth=6)
        decisions = previous.get("decisions", []) if isinstance(previous, dict) else []
        decisions = [item for item in decisions if isinstance(item, dict)]
        decisions += [
            {"block_id": edit.block_id, "action": action, "provider": edit.provider}
            for edit in edits
        ]
        write_json(path, {"schema_version": 1, "decisions": decisions})
    except Exception:
        return


def accept_edits(manifest_path: Path, block_ids: Sequence[str] | None) -> list[str]:
    """Accept pending edits (all when ``block_ids`` is None); returns the accepted block IDs."""
    folder = manifest_path.parent
    with workspace_lock(folder):
        manifest = read_manifest(manifest_path)
        chosen = _select(manifest, block_ids, "accept")
        if not chosen:
            return []
        policy = resolve_footnote_policy(manifest, folder)
        for edit in chosen:
            edit.accepted = True
        # Plans every chapter first and publishes the manifest and texts together, or
        # raises the content-free chapter conflict before anything is written.
        render_chapter_texts(manifest, folder, policy, commit_manifest=True)
        _audit(folder, "accepted", chosen)
        return [edit.block_id for edit in chosen]


def reject_edits(manifest_path: Path, block_ids: Sequence[str] | None) -> list[str]:
    """Remove pending edits; chapter text is unaffected because proposals never changed it."""
    folder = manifest_path.parent
    with workspace_lock(folder):
        manifest = read_manifest(manifest_path)
        chosen = _select(manifest, block_ids, "reject")
        if not chosen:
            return []
        manifest.edits = [edit for edit in manifest.edits if edit not in chosen]
        write_manifest(manifest_path, manifest)
        _audit(folder, "rejected", chosen)
        return [edit.block_id for edit in chosen]
