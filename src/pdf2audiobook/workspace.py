"""Transactional local workspace persistence."""

import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pdf2audiobook.errors import ExtractionError, WorkspaceError, WorkspaceLockedError
from pdf2audiobook.models import BookManifest

_workspace_locks = threading.local()


@contextmanager
def workspace_lock(folder: Path, *, blocking: bool = False) -> Iterator[None]:
    """Hold the per-book lock used by analysis, conversion and review writes."""
    lock_key = folder.resolve()
    held: set[Path] = getattr(_workspace_locks, "held", set())
    if lock_key in held:
        yield
        return
    try:
        import fcntl
    except ImportError:  # pragma: no cover - platforms without POSIX file locks
        yield
        return
    try:
        folder.mkdir(parents=True, exist_ok=True)
        handle = (folder / ".convert.lock").open("a+")
    except OSError:
        raise WorkspaceError("Cannot create the output workspace") from None
    try:
        operation = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(handle, operation)
        except OSError:
            raise WorkspaceLockedError(
                "Another conversion is already running for this book"
            ) from None
        _workspace_locks.held = {*held, lock_key}
        try:
            yield
        finally:
            _workspace_locks.held = held
    finally:
        handle.close()


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_file(path: Path) -> str:
    """Hash large inputs and cached outputs without loading them into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(*parts: Any) -> str:
    return digest_bytes(json.dumps(parts, sort_keys=True, default=str).encode())


def atomic_write(path: Path, data: bytes) -> None:
    temp_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".tmp-", delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except OSError:
        raise WorkspaceError("Cannot create the output workspace") from None
    finally:
        if temp_path:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def write_json(path: Path, obj: Any) -> None:
    # Standard JSON has no NaN/Infinity tokens. Serialize before touching
    # the destination so a malformed report cannot replace a valid artifact.
    atomic_write(
        path, (json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    )


def read_manifest(path: Path) -> BookManifest:
    """Fail closed without disclosing user book content or private file paths."""
    try:
        return BookManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Pydantic diagnostics can include untrusted field values and input
        # fragments; filesystem exceptions may contain private workspace paths.
        # Preserve the existing manifest for user recovery on read failures.
        raise ExtractionError(
            "Cannot read or validate audiobook manifest; re-run analyze with a new output directory"
        ) from None


def write_manifest(path: Path, manifest: BookManifest) -> None:
    write_json(path, manifest.model_dump(mode="json"))
