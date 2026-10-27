"""Recoverable publication of reviewed manifests and their chapter artifacts."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
from pathlib import Path
from typing import Any

from pdf2audiobook.chapter_artifacts import STATE_NAME, ArtifactPlan, _read_digest
from pdf2audiobook.errors import ExtractionError, PendingRecoveryError
from pdf2audiobook.jsonio import load_bounded_json
from pdf2audiobook.models import BookManifest
from pdf2audiobook.workspace import REVIEW_JOURNAL, atomic_write, digest_bytes

JOURNAL = REVIEW_JOURNAL
_TARGET = re.compile(
    r"(?:manifest\.json|coverage\.json|chapter-artifacts\.json|chapters/[0-9]{3,}\.txt)\Z"
)
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class ReviewRecoveryRequired(ExtractionError):
    """A review was committed but its artifacts require recovery."""


def _sync_directory(path: Path) -> None:
    if os.name == "nt":  # Windows does not expose directory fsync via os.open.
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def _target(folder: Path, name: str) -> Path:
    if not _TARGET.fullmatch(name):
        raise ExtractionError("Review transaction is invalid; restore the workspace from backup")
    target = folder / name
    if target.parent != folder and target.parent.is_symlink():
        raise ExtractionError("Review transaction has an unsafe workspace target")
    return target


def _recover(folder: Path, record: dict[str, Any]) -> None:
    entries = record.get("entries")
    if (
        set(record) != {"version", "entries"}
        or record.get("version") != 1
        or not isinstance(entries, list)
        or len(entries) > 100000
    ):
        raise ExtractionError("Review transaction is invalid; restore the workspace from backup")
    validated: list[tuple[Path, str | None, str | None, bytes | None]] = []
    seen: set[str] = set()
    for row in entries:
        if not isinstance(row, dict) or set(row) != {"target", "old", "new", "data"}:
            raise ExtractionError(
                "Review transaction is invalid; restore the workspace from backup"
            )
        name, old, new, encoded = (row[key] for key in ("target", "old", "new", "data"))
        if (
            not isinstance(name, str)
            or name in seen
            or not (encoded is None or isinstance(encoded, str))
            or any(
                value is not None and (not isinstance(value, str) or not _HASH.fullmatch(value))
                for value in (old, new)
            )
        ):
            raise ExtractionError(
                "Review transaction is invalid; restore the workspace from backup"
            )
        seen.add(name)
        target = _target(folder, name)
        try:
            data = base64.b64decode(encoded, validate=True) if isinstance(encoded, str) else None
        except (ValueError, binascii.Error):
            raise ExtractionError(
                "Review transaction is invalid; restore the workspace from backup"
            ) from None
        if (data is None) != (new is None) or (data is not None and digest_bytes(data) != new):
            raise ExtractionError(
                "Review transaction is invalid; restore the workspace from backup"
            )
        current = _read_digest(target)
        if current not in (old, new):
            raise ExtractionError(
                "Review recovery found changed workspace files; restore them from backup"
            )
        validated.append((target, old, new, data))
    if not {"coverage.json", STATE_NAME}.issubset(seen):
        raise ExtractionError("Review transaction is invalid; restore the workspace from backup")
    for target, old, new, data in validated:
        current = _read_digest(target)
        if current == new:
            continue
        if current != old:
            raise ExtractionError(
                "Review recovery found changed workspace files; restore them from backup"
            )
        if data is None:
            target.unlink(missing_ok=True)
        else:
            atomic_write(target, data)
        _sync_directory(target.parent)
    # Persist any newly created chapter directory before removing the journal.
    _sync_directory(folder)
    (folder / JOURNAL).unlink(missing_ok=True)
    _sync_directory(folder)


def recover_review_transaction(folder: Path) -> None:
    path = folder / JOURNAL
    if not path.exists() and not path.is_symlink():
        return
    try:
        if path.is_symlink() or not path.is_file():
            raise ExtractionError("Invalid transaction")
        record = load_bounded_json(path, max_bytes=512 * 1024 * 1024, max_depth=8)
        if not isinstance(record, dict):
            raise ExtractionError("Invalid transaction")
        _recover(folder, record)
    except Exception:
        raise PendingRecoveryError(
            "A previous workspace update needs recovery; this operation was not performed. "
            "Restore changed files or a backup, then retry"
        ) from None


def commit_review(
    manifest_path: Path, manifest: BookManifest, plan: ArtifactPlan, *, expected_manifest: str
) -> None:
    if manifest_path.name != "manifest.json":
        raise ExtractionError("Review requires a manifest.json workspace")
    commit_artifacts(
        manifest_path.parent, plan, manifest=manifest, expected_manifest=expected_manifest
    )


def commit_artifacts(
    folder: Path,
    plan: ArtifactPlan,
    *,
    manifest: BookManifest | None = None,
    expected_manifest: str | None = None,
) -> None:
    """Commit a guarded artifact set, optionally including its manifest."""
    payloads: dict[str, bytes | None] = {
        "coverage.json": _json_bytes(plan.coverage),
        STATE_NAME: _json_bytes(plan.state),
        **{f"chapters/{name}": data for name, data in plan.writes.items()},
        **{f"chapters/{name}": None for name in plan.deletes},
    }
    if manifest is not None:
        payloads = {"manifest.json": _json_bytes(manifest.model_dump(mode="json")), **payloads}
    entries = []
    for name, data in payloads.items():
        path = _target(folder, name)
        current = _read_digest(path)
        if name in plan.metadata_observed and current != plan.metadata_observed[name]:
            raise ExtractionError("Chapter metadata changed during planning; retry")
        if (
            name == "manifest.json"
            and expected_manifest is not None
            and current != expected_manifest
        ):
            raise ExtractionError("Manifest changed during review; retry")
        if name.startswith("chapters/") and current != plan.observed[name[9:]]:
            raise ExtractionError("Chapter text changed during review; retry")
        entries.append(
            {
                "target": name,
                "old": current,
                "new": digest_bytes(data) if data is not None else None,
                "data": base64.b64encode(data).decode("ascii") if data is not None else None,
            }
        )
    for name, expected in plan.observed.items():
        if _read_digest(_target(folder, f"chapters/{name}")) != expected:
            raise ExtractionError("Chapter text changed during review; retry")
    record = {"version": 1, "entries": entries}
    journal = folder / JOURNAL
    encoded = _json_bytes(record)
    if len(encoded) > 512 * 1024 * 1024:
        raise ExtractionError("Chapter transaction exceeds the workspace size limit")
    atomic_write(journal, encoded)
    try:
        _sync_directory(folder)
        _recover(folder, record)
    except Exception:
        raise ReviewRecoveryRequired(
            "Workspace update was committed but needs recovery; retry the workspace operation"
        ) from None
