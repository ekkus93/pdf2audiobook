"""Publish a chapter's new MP3 and sidecar together, keeping the previous ones as a backup.

Verification spec §6 / AV4: replacement audio is made in temporary files, the current MP3 is
replaced only after the new one is encoded and checked, and the previous MP3 and sidecar stay
recoverable. The new files are staged in `audio/.staging/`; the old ones are linked into
`audio/.backup/`; a small journal names the two renames; then both files are renamed into
place and the journal is removed. If the process dies after the journal is written, the next
conversion finishes the renames (both staged files were already checked), so the chapter is
never left with an MP3 and a sidecar that don't belong together.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pdf2audiobook.errors import AudioError
from pdf2audiobook.logging import log_event
from pdf2audiobook.workspace import atomic_write, digest_file

STAGING = ".staging"
BACKUP = ".backup"
# Backups kept per chapter file name; older ones are removed.
KEEP_BACKUPS = 3
_JOURNAL_PREFIX = ".commit-"


def staged_path(output: Path) -> Path:
    """Where a chapter's new MP3 is encoded before it may replace `output`."""
    return output.parent / STAGING / output.name


def _journal(output: Path) -> Path:
    key = hashlib.sha256(output.name.encode("utf-8")).hexdigest()[:16]
    return output.parent / f"{_JOURNAL_PREFIX}{key}.json"


def _link_or_copy(source: Path, target: Path) -> None:
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def _backup(output: Path, record: Path) -> Path | None:
    """Keep the current MP3 and sidecar under `.backup/`; return the backup MP3, if any."""
    if not output.is_file() or output.is_symlink():
        return None
    folder = output.parent / BACKUP
    folder.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = folder / f"{output.stem}.{stamp}{output.suffix}"
    _link_or_copy(output, target)
    if record.is_file() and not record.is_symlink():
        _link_or_copy(record, target.with_suffix(".cache.json"))
    old = sorted(folder.glob(f"{output.stem}.*{output.suffix}"))
    for stale in old[:-KEEP_BACKUPS]:
        stale.unlink(missing_ok=True)
        stale.with_suffix(".cache.json").unlink(missing_ok=True)
    return target


def _cleanup_staged(staged: Path) -> None:
    staged.unlink(missing_ok=True)
    staged.with_suffix(".cache.json").unlink(missing_ok=True)


def discard_staged(output: Path) -> None:
    """Remove a staged MP3 that will not be committed (failed or interrupted synthesis)."""
    with contextlib.suppress(OSError):
        _cleanup_staged(staged_path(output))


def commit_chapter_audio(output: Path, record: Path, sidecar: dict[str, Any]) -> Path | None:
    """Replace `output` and `record` with the staged MP3 and `sidecar`; return the backup MP3.

    `sidecar` must not yet hold the MP3's hash and size; they are taken from the staged file.
    On any failure before the renames, the staged files are removed and the current audio is
    untouched; the error holds no path.
    """
    staged = staged_path(output)
    staged_record = staged.with_suffix(".cache.json")
    journal = _journal(output)
    try:
        data = {**sidecar, "sha256": digest_file(staged), "bytes": staged.stat().st_size}
        atomic_write(staged_record, (json.dumps(data, indent=2, allow_nan=False) + "\n").encode())
        backup = _backup(output, record)
        atomic_write(
            journal,
            json.dumps({"output": output.name, "record": record.name}).encode(),
        )
    except (OSError, ValueError):
        _cleanup_staged(staged)
        raise AudioError(
            "Could not stage the new chapter audio; the previous audio is kept"
        ) from None
    _finish(journal)
    return backup


def _finish(journal: Path) -> None:
    """Rename the staged MP3, then its sidecar, into place; then drop the journal."""
    entry = json.loads(journal.read_text(encoding="utf-8"))
    folder = journal.parent
    output, record = folder / entry["output"], folder / entry["record"]
    staged = staged_path(output)
    try:
        if staged.exists():
            os.replace(staged, output)
        if staged.with_suffix(".cache.json").exists():
            os.replace(staged.with_suffix(".cache.json"), record)
    except OSError:
        raise AudioError(
            "Could not publish the new chapter audio; run the conversion again"
        ) from None
    journal.unlink(missing_ok=True)


def recover_audio_commits(audio_folder: Path) -> int:
    """Finish renames a stopped conversion left journaled; drop leftover staged files.

    Called before conversion. Returns how many commits were finished.
    """
    finished = 0
    if not audio_folder.is_dir():
        return 0
    for journal in sorted(audio_folder.glob(f"{_JOURNAL_PREFIX}*.json")):
        try:
            _finish(journal)
            finished += 1
        except (OSError, ValueError, KeyError, AudioError):
            log_event("audio_commit_recovery_failed", level=logging.WARNING)
    staging = audio_folder / STAGING
    if staging.is_dir():
        # Not journaled: never committed, so not trusted; the conversion makes them again.
        for leftover in staging.iterdir():
            with contextlib.suppress(OSError):
                if leftover.is_dir():
                    shutil.rmtree(leftover)
                else:
                    leftover.unlink()
    # Temporary encode folders a killed run left next to the chapters (AV0.01).
    for leftover in audio_folder.glob("tmp*"):
        if leftover.is_dir() and not leftover.is_symlink():
            shutil.rmtree(leftover, ignore_errors=True)
    return finished
