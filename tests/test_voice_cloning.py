"""Offline voice selection, immutable references, artifact setup and worker safety."""

import hashlib
import io
import os
from pathlib import Path

import pytest

from pdf2audiobook.errors import AudioError
from pdf2audiobook.tts import catalog


def test_model_fetch_is_verified_atomic_and_cancel_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = {
        "repo": catalog.MODEL_ID,
        "revision": "a" * 40,
        "name": "weights.bin",
        "size": 3,
        "sha256": hashlib.sha256(b"abc").hexdigest(),
    }
    monkeypatch.setitem(catalog.MANIFEST, "files", [artifact])
    root = tmp_path / "models"
    assert catalog.fetch_model(root, opener=lambda *a, **kw: io.BytesIO(b"abc")) == ["weights.bin"]
    assert catalog.verified(artifact, root)
    assert catalog.fetch_model(root, opener=lambda *a, **kw: pytest.fail("downloaded twice")) == []
    target = catalog.artifact_path(artifact, root)
    before = target.stat()
    target.write_bytes(b"def")
    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert not catalog.verified(artifact, root)
    with pytest.raises(AudioError):
        catalog.fetch_model(root, opener=lambda *a, **kw: io.BytesIO(b"BAD"))
    assert target.read_bytes() == b"def"
    assert not list(root.rglob(".part-*"))


def test_download_interruption_removes_unpublished_files(tmp_path, monkeypatch):
    artifact = {
        "repo": catalog.MODEL_ID,
        "revision": catalog.MODEL_REVISION,
        "name": "weights",
        "size": 4,
        "sha256": hashlib.sha256(b"data").hexdigest(),
    }
    monkeypatch.setitem(catalog.MANIFEST, "files", [artifact])

    class Interrupted(io.BytesIO):
        def read(self, size=-1):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        catalog.fetch_model(tmp_path, opener=lambda *a, **kw: Interrupted(b"data"))
    assert not list(tmp_path.rglob(".part-*"))
    assert not catalog.artifact_path(artifact, tmp_path).exists()
