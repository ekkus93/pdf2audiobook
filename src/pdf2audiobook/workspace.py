"""Transactional local workspace persistence."""
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pdf2audiobook.models import BookManifest


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
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".tmp-", delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


def write_json(path: Path, obj: Any) -> None:
    atomic_write(path, (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode())


def read_manifest(path: Path) -> BookManifest:
    return BookManifest.model_validate_json(path.read_text(encoding="utf-8"))


def write_manifest(path: Path, manifest: BookManifest) -> None:
    write_json(path, manifest.model_dump(mode="json"))
