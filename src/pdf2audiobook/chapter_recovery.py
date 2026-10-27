"""Explicit recovery for chapter files that block planning or review."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pdf2audiobook.chapter_artifacts import (
    find_chapter_conflicts,
    load_artifact_state,
    plan_chapter_artifacts,
    resolve_footnote_policy,
)
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.review_transaction import commit_artifacts
from pdf2audiobook.workspace import backup_file, read_manifest, workspace_lock


@dataclass(frozen=True)
class RegenerationResult:
    regenerated: tuple[int, ...]
    backed_up: tuple[int, ...]
    backup_files: tuple[str, ...]


def regenerate_chapters(
    manifest_path: Path,
    numbers: Sequence[int],
    *,
    all_conflicts: bool,
    footnotes: str | None = None,
) -> RegenerationResult:
    """Replace chapter files with generated text, backing up any differing file first.

    Runs under the workspace lock, which first completes or refuses any pending
    transaction. Approvals, review reasons and the manifest are never changed.
    ``footnotes`` supplies the policy for a legacy workspace that has none recorded
    and whose files do not reveal it; it may not contradict a recorded policy.
    """
    folder = manifest_path.parent
    chapter_dir = folder / "chapters"
    with workspace_lock(folder):
        manifest = read_manifest(manifest_path)
        state = load_artifact_state(folder)
        if state is not None:
            policy = state["footnotes"]
            if footnotes is not None and footnotes != policy:
                raise ExtractionError(
                    "A footnote policy is already recorded for this workspace; "
                    "change it by running analyze with the new pdf.footnotes setting"
                )
        else:
            policy = (
                footnotes if footnotes is not None else resolve_footnote_policy(manifest, folder)
            )
        if all_conflicts:
            selected = find_chapter_conflicts(manifest, folder, policy)
        else:
            selected = sorted(set(numbers))
            known = {chapter.number for chapter in manifest.chapters}
            for number in selected:
                if number not in known and not (chapter_dir / f"{number:03d}.txt").is_file():
                    raise ExtractionError(f"Chapter {number} does not exist in this workspace")
        if not selected:
            return RegenerationResult((), (), ())
        plan = plan_chapter_artifacts(manifest, folder, policy, force=frozenset(selected))
        known = {chapter.number for chapter in manifest.chapters}
        backed_up: list[int] = []
        backup_files: list[str] = []
        # Back up before the commit point; backups are never removed by this tool.
        for number in selected:
            name = f"{number:03d}.txt"
            path = chapter_dir / name
            if not path.exists():
                continue
            if number in known and name not in plan.writes:
                continue  # already matches the generated text
            backup_files.append(
                backup_file(
                    folder, path, subdir="chapter-backups", stem=f"{number:03d}", suffix=".txt"
                )
            )
            backed_up.append(number)
        commit_artifacts(folder, plan)
    return RegenerationResult(tuple(selected), tuple(backed_up), tuple(backup_files))
