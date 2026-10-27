"""Recoverable publication of reviewed manifests and their chapter artifacts."""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdf2audiobook.chapter_artifacts import STATE_NAME, ArtifactPlan, _read_digest
from pdf2audiobook.errors import ExtractionError, PendingRecoveryError
from pdf2audiobook.jsonio import load_bounded_json
from pdf2audiobook.models import BookManifest
from pdf2audiobook.workspace import REVIEW_JOURNAL, atomic_write, backup_file, digest_bytes
from pdf2audiobook.workspace import sync_directory as _sync_directory

JOURNAL = REVIEW_JOURNAL
_TARGET = re.compile(
    r"(?:manifest\.json|coverage\.json|chapter-artifacts\.json|chapters/[0-9]{3,}\.txt)\Z"
)
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class ReviewRecoveryRequired(ExtractionError):
    """A review was committed but its artifacts require recovery."""


class _InvalidTransaction(ExtractionError):
    """The journal is malformed or unsafe; never repaired automatically."""


class _RecoveryBlocked(Exception):
    """Targets changed after the committed update; carries their safe labels."""

    def __init__(self, labels: list[str]):
        super().__init__()
        self.labels = labels


@dataclass(frozen=True)
class RecoveryReport:
    status: str  # "nothing_pending" or "recovered"
    backed_up: tuple[str, ...] = ()  # safe labels such as "chapter 1"
    backup_files: tuple[str, ...] = ()  # workspace-relative backup names


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def _label(name: str) -> str:
    """Describe a target without exposing paths, digests or text."""
    if name.startswith("chapters/"):
        return f"chapter {int(name[9:-4])}"
    return {
        "manifest.json": "manifest",
        "coverage.json": "coverage report",
        STATE_NAME: "chapter metadata",
    }[name]


def _target(folder: Path, name: str) -> Path:
    if not _TARGET.fullmatch(name):
        raise _InvalidTransaction(
            "Review transaction is invalid; restore the workspace from backup"
        )
    target = folder / name
    if target.parent != folder and target.parent.is_symlink():
        raise _InvalidTransaction("Review transaction has an unsafe workspace target")
    return target


def _back_up_target(folder: Path, name: str, target: Path) -> str:
    if name.startswith("chapters/"):
        return backup_file(folder, target, subdir="chapter-backups", stem=name[9:-4], suffix=".txt")
    return backup_file(folder, target, subdir="workspace-backups", stem=name)


def _recover(
    folder: Path, record: dict[str, Any], *, back_up_changed: bool = False
) -> tuple[list[str], list[str]]:
    """Complete a committed transaction; return the (labels, files) of backed-up targets."""
    entries = record.get("entries")
    if (
        set(record) != {"version", "entries"}
        or record.get("version") != 1
        or not isinstance(entries, list)
        or len(entries) > 100000
    ):
        raise _InvalidTransaction(
            "Review transaction is invalid; restore the workspace from backup"
        )
    validated: list[tuple[str, Path, str | None, str | None, bytes | None]] = []
    blocked: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for row in entries:
        if not isinstance(row, dict) or set(row) != {"target", "old", "new", "data"}:
            raise _InvalidTransaction(
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
            raise _InvalidTransaction(
                "Review transaction is invalid; restore the workspace from backup"
            )
        seen.add(name)
        target = _target(folder, name)
        try:
            data = base64.b64decode(encoded, validate=True) if isinstance(encoded, str) else None
        except (ValueError, binascii.Error):
            raise _InvalidTransaction(
                "Review transaction is invalid; restore the workspace from backup"
            ) from None
        if (data is None) != (new is None) or (data is not None and digest_bytes(data) != new):
            raise _InvalidTransaction(
                "Review transaction is invalid; restore the workspace from backup"
            )
        current = _read_digest(target)
        if current not in (old, new):
            blocked.append((name, target))
        validated.append((name, target, old, new, data))
    if not {"coverage.json", STATE_NAME}.issubset(seen):
        raise _InvalidTransaction(
            "Review transaction is invalid; restore the workspace from backup"
        )
    forced: set[Path] = set()
    labels: list[str] = []
    files: list[str] = []
    if blocked:
        if not back_up_changed:
            raise _RecoveryBlocked([_label(name) for name, _ in blocked])
        # Keep every changed file before anything is overwritten.
        for name, target in blocked:
            if target.exists():
                files.append(_back_up_target(folder, name, target))
            labels.append(_label(name))
            forced.add(target)
    for name, target, old, new, data in validated:
        current = _read_digest(target)
        if current == new:
            continue
        if current != old and target not in forced:
            raise _RecoveryBlocked([_label(name)])
        if data is None:
            target.unlink(missing_ok=True)
        else:
            atomic_write(target, data)
        _sync_directory(target.parent)
    # Persist any newly created chapter directory before removing the journal.
    _sync_directory(folder)
    (folder / JOURNAL).unlink(missing_ok=True)
    _sync_directory(folder)
    return labels, files


def recover_review_transaction(folder: Path, *, back_up_changed: bool = False) -> RecoveryReport:
    path = folder / JOURNAL
    if not path.exists() and not path.is_symlink():
        return RecoveryReport("nothing_pending")
    try:
        if path.is_symlink() or not path.is_file():
            raise _InvalidTransaction("Invalid transaction")
        record = load_bounded_json(path, max_bytes=512 * 1024 * 1024, max_depth=8)
        if not isinstance(record, dict):
            raise _InvalidTransaction("Invalid transaction")
        labels, files = _recover(folder, record, back_up_changed=back_up_changed)
    except _RecoveryBlocked as blocked:
        raise PendingRecoveryError(
            "A previous workspace update needs recovery; this operation was not performed. "
            f"Changed since that update: {', '.join(blocked.labels)}. Run pdf2audiobook recover "
            "--back-up-changed on the manifest to keep copies and finish, or restore them "
            "from a backup",
            labels=blocked.labels,
        ) from None
    except _InvalidTransaction:
        raise PendingRecoveryError(
            "The pending workspace update record is invalid; restore the workspace from a backup"
        ) from None
    except Exception:
        raise PendingRecoveryError(
            "A previous workspace update could not be completed; this operation was not "
            "performed. Retry, or restore the workspace from a backup"
        ) from None
    return RecoveryReport("recovered", tuple(labels), tuple(files))


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
    except _RecoveryBlocked as blocked:
        raise ReviewRecoveryRequired(
            "Workspace update was committed but needs recovery "
            f"({', '.join(blocked.labels)} changed); run pdf2audiobook recover on the manifest"
        ) from None
    except Exception:
        raise ReviewRecoveryRequired(
            "Workspace update was committed but needs recovery; retry the workspace operation"
        ) from None
