"""Plan chapter text updates without replacing potentially edited files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdf2audiobook.document.structure import chapter_coverage_report, render_chapter_narration
from pdf2audiobook.errors import ChapterConflictError, ExtractionError
from pdf2audiobook.jsonio import load_bounded_json
from pdf2audiobook.models import BookManifest, Chapter
from pdf2audiobook.workspace import digest_bytes, fingerprint

_POLICIES = {"warn", "inline", "end", "omit"}
_CHAPTER_NAME = re.compile(r"[0-9]{3,}\.txt\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
STATE_NAME = "chapter-artifacts.json"


@dataclass(frozen=True)
class ArtifactPlan:
    """Complete proposed changes and observed contents for guarded publication."""

    writes: dict[str, bytes]
    deletes: tuple[str, ...]
    observed: dict[str, str | None]
    metadata_observed: dict[str, str | None]
    state: dict[str, Any]
    coverage: dict[str, object]


def _conflict(number: int) -> ChapterConflictError:
    return ChapterConflictError(number)


def _read_digest(path: Path) -> str | None:
    try:
        if not path.exists() and not path.is_symlink():
            return None
        if path.is_symlink() or not path.is_file():
            raise OSError("unsupported chapter file")
        from pdf2audiobook.workspace import digest_file

        return digest_file(path)
    except OSError:
        raise ExtractionError("Cannot inspect chapter text; check workspace files") from None


def _identity(manifest: BookManifest, chapter: Chapter, policy: str) -> str:
    blocks = manifest.blocks[chapter.start_block : chapter.end_block]
    ids = {block.id for block in blocks}
    edits = [
        edit.model_dump(mode="json")
        for edit in manifest.edits
        if edit.accepted and edit.block_id in ids
    ]
    # Reflow also considers supporting text across the entire book.
    return fingerprint(
        "chapter-render-v1",
        chapter.start_block,
        chapter.end_block,
        policy,
        [block.model_dump(mode="json") for block in blocks],
        edits,
        [block.text for block in manifest.blocks],
    )


def load_artifact_state(folder: Path) -> dict[str, Any] | None:
    path = folder / STATE_NAME
    if not path.exists() and not path.is_symlink():
        return None
    raw = load_bounded_json(path, max_bytes=4 * 1024 * 1024, max_depth=8)
    if not isinstance(raw, dict) or set(raw) != {"version", "footnotes", "chapters"}:
        raise ExtractionError("Chapter artifact metadata is invalid; restore it from a backup")
    chapters = raw.get("chapters")
    if (
        raw.get("version") != 1
        or not isinstance(raw.get("footnotes"), str)
        or raw.get("footnotes") not in _POLICIES
        or not isinstance(chapters, dict)
    ):
        raise ExtractionError("Chapter artifact metadata is invalid; restore it from a backup")
    numbers: set[int] = set()
    for chapter_id, record in chapters.items():
        if (
            not isinstance(chapter_id, str)
            or not isinstance(record, dict)
            or set(record) != {"number", "generated", "identity", "edited"}
            or isinstance(record.get("number"), bool)
            or not isinstance(record.get("number"), int)
            or record["number"] < 1
            or record["number"] in numbers
            or not isinstance(record.get("generated"), str)
            or not _DIGEST.fullmatch(record["generated"])
            or not isinstance(record.get("identity"), str)
            or not _DIGEST.fullmatch(record["identity"])
            or not isinstance(record.get("edited"), bool)
        ):
            raise ExtractionError("Chapter artifact metadata is invalid; restore it from a backup")
        numbers.add(record["number"])
    return raw


def _flag(conflicts: list[int] | None, number: int) -> None:
    """Raise the conflict, or record it when the caller is collecting conflicts."""
    if conflicts is None:
        raise _conflict(number)
    if number not in conflicts:
        conflicts.append(number)


def plan_chapter_artifacts(
    manifest: BookManifest, folder: Path, policy: str, *, force: frozenset[int] = frozenset()
) -> ArtifactPlan:
    """Validate all chapter changes and return a plan without writing anything.

    ``force`` names chapter numbers whose files the caller has already backed up
    and wants replaced by generated text, so they are never reported as conflicts.
    """
    return _plan(manifest, folder, policy, force, None)


def find_chapter_conflicts(manifest: BookManifest, folder: Path, policy: str) -> list[int]:
    """Return every chapter number the planner would currently refuse, in order."""
    conflicts: list[int] = []
    _plan(manifest, folder, policy, frozenset(), conflicts)
    return sorted(conflicts)


def _plan(
    manifest: BookManifest,
    folder: Path,
    policy: str,
    force: frozenset[int],
    conflicts: list[int] | None,
) -> ArtifactPlan:
    if policy not in _POLICIES:
        raise ExtractionError("Chapter footnote policy is invalid")
    coverage = chapter_coverage_report(manifest)
    metadata_observed = {
        STATE_NAME: _read_digest(folder / STATE_NAME),
        "coverage.json": _read_digest(folder / "coverage.json"),
    }
    state = load_artifact_state(folder)
    if _read_digest(folder / STATE_NAME) != metadata_observed[STATE_NAME]:
        raise ExtractionError("Chapter artifact metadata changed during planning; retry")
    previous = state["chapters"] if state else {}
    if len({chapter.id for chapter in manifest.chapters}) != len(manifest.chapters):
        raise ExtractionError("Duplicate chapter IDs in manifest")
    old_by_number = {record["number"]: (key, record) for key, record in previous.items()}
    chapter_dir = folder / "chapters"
    new_numbers = {chapter.id: chapter.number for chapter in manifest.chapters}
    for chapter_id, record in previous.items():
        if new_numbers.get(chapter_id) == record["number"]:
            continue
        if record["number"] in force:
            continue
        actual = _read_digest(chapter_dir / f"{record['number']:03d}.txt")
        if record["edited"] or (actual is not None and actual != record["generated"]):
            _flag(conflicts, record["number"])
    observed: dict[str, str | None] = {}
    writes: dict[str, bytes] = {}
    records: dict[str, dict[str, Any]] = {}
    current_names: set[str] = set()
    for chapter in manifest.chapters:
        name = f"{chapter.number:03d}.txt"
        current_names.add(name)
        content = render_chapter_narration(manifest, chapter, policy).encode("utf-8")
        generated = digest_bytes(content)
        identity = _identity(manifest, chapter, policy)
        actual = _read_digest(chapter_dir / name)
        observed[name] = actual
        old = previous.get(chapter.id)
        occupant = old_by_number.get(chapter.number)
        if chapter.number in force:
            edited = False
        elif (
            occupant
            and occupant[0] != chapter.id
            and actual is not None
            and (actual != occupant[1]["generated"] or occupant[1]["edited"])
        ):
            _flag(conflicts, chapter.number)
            continue
        elif old is None or old["number"] != chapter.number:
            if actual is not None and actual != generated and not occupant:
                _flag(conflicts, chapter.number)
                continue
            edited = False
        else:
            if actual is None and old["edited"]:
                _flag(conflicts, chapter.number)
                continue
            edited = actual is not None and actual != old["generated"]
            if edited and old["identity"] != identity:
                _flag(conflicts, chapter.number)
                continue
        if not edited and actual != generated:
            writes[name] = content
        records[chapter.id] = {
            "number": chapter.number,
            "generated": generated,
            "identity": identity,
            "edited": edited,
        }
    deletes: list[str] = []
    if chapter_dir.exists():
        for path in chapter_dir.iterdir():
            if not _CHAPTER_NAME.fullmatch(path.name) or path.name in current_names:
                continue
            actual = _read_digest(path)
            observed[path.name] = actual
            old_entry = next(
                (r for r in previous.values() if f"{r['number']:03d}.txt" == path.name), None
            )
            if int(path.stem) not in force and (
                old_entry is None or old_entry["edited"] or actual != old_entry["generated"]
            ):
                _flag(conflicts, int(path.stem))
                continue
            deletes.append(path.name)
    return ArtifactPlan(
        writes,
        tuple(deletes),
        observed,
        metadata_observed,
        {"version": 1, "footnotes": policy, "chapters": records},
        coverage,
    )
