"""A damaged cached model file is rejected and fetched again, never trusted (real-model CI 3.3).

The real-model workflow restores model directories from `actions/cache`. These tests truncate or
alter a restored file and check the project's own readiness and fetch code, offline.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any

import pytest

from pdf2audiobook.tts import catalog
from pdf2audiobook.verification import models
from pdf2audiobook.verification.models import ModelSpec, PinnedFile

WEIGHTS = b"pretend model weights, long enough to truncate"


class _Server:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.requests: list[str] = []

    def __call__(self, url: str, **_: Any) -> io.BytesIO:
        self.requests.append(url)
        return io.BytesIO(self.files[url])


def _asr_setup(monkeypatch: pytest.MonkeyPatch) -> tuple[PinnedFile, _Server]:
    pinned = PinnedFile(
        "model.pt",
        "https://models.example/model.pt",
        len(WEIGHTS),
        hashlib.sha256(WEIGHTS).hexdigest(),
    )
    monkeypatch.setitem(
        models.SPECS,
        "whisper",
        ModelSpec("whisper", "OpenAI Whisper", "medium.en", "r", ("pytest",), (pinned,)),
    )
    return pinned, _Server({pinned.url: WEIGHTS})


def test_a_truncated_cached_asr_file_is_refetched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pinned, server = _asr_setup(monkeypatch)
    root = tmp_path / "asr"
    models.fetch("whisper", root, opener=server)
    assert models.readiness("whisper", root).ready
    cached = root / "whisper" / pinned.name

    # What a cache restore could hand back: a cut-off file whose stamp still looks valid.
    cached.write_bytes(WEIGHTS[: len(WEIGHTS) // 2])
    assert cached.with_name(cached.name + ".sha256").read_text().strip() == pinned.sha256

    assert not models.readiness("whisper", root).ready
    assert [f.name for f in models.fetch("whisper", root, opener=server)] == [pinned.name]
    assert cached.read_bytes() == WEIGHTS
    assert models.readiness("whisper", root).ready
    assert len(server.requests) == 2


def test_a_truncated_cached_kitten2_file_is_rejected_and_refetched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    artifact = {
        "repo": catalog.MODEL_ID,
        "revision": "test",
        "name": "weights.bin",
        "size": len(WEIGHTS),
        "sha256": hashlib.sha256(WEIGHTS).hexdigest(),
    }
    monkeypatch.setitem(catalog.MANIFEST, "files", [artifact])
    url = f"https://huggingface.co/{artifact['repo']}/resolve/test/weights.bin"
    server = _Server({url: WEIGHTS})
    root = tmp_path / "kitten2"

    assert catalog.fetch_model(root, opener=server) == ["weights.bin"]
    assert catalog.missing_files(root) == []

    cached = catalog.artifact_path(artifact, root)
    cached.write_bytes(WEIGHTS[:10])
    assert catalog.missing_files(root) == [artifact]
    assert catalog.fetch_model(root, opener=server) == ["weights.bin"]
    assert cached.read_bytes() == WEIGHTS
    assert catalog.missing_files(root) == []

    # Same size, different bytes: the Kitten 2 check rehashes, so it is rejected too.
    cached.write_bytes(b"X" * len(WEIGHTS))
    assert catalog.missing_files(root) == [artifact]
    assert catalog.fetch_model(root, opener=server) == ["weights.bin"]
    assert cached.read_bytes() == WEIGHTS
    assert len(server.requests) == 3
