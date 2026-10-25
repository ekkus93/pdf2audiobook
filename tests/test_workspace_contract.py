import json
from pathlib import Path

import pytest

from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.models import BookManifest
from pdf2audiobook.workspace import atomic_write, fingerprint, read_manifest, write_manifest


def test_manifest_schema_version_is_rejected(tmp_path: Path):
    path = tmp_path / "manifest.json"
    manifest = BookManifest(
        schema_version=2, input_sha256="a" * 64, title="Test", source_path="input.pdf"
    )
    write_manifest(path, manifest)
    assert read_manifest(path).schema_version == 2
    data = json.loads(path.read_text())
    data["schema_version"] = 999
    path.write_text(json.dumps(data))
    with pytest.raises(ExtractionError, match="Cannot read or validate audiobook manifest") as exc:
        read_manifest(path)
    assert exc.value.__suppress_context__ is True
    assert path.read_text(encoding="utf-8") == json.dumps(data)


def test_schema_v2_round_trips_chapter_warnings_and_generated_fingerprint(tmp_path: Path):
    path = tmp_path / "manifest.json"
    manifest = BookManifest(
        schema_version=2,
        input_sha256="b" * 64,
        title="Test",
        source_path="input.pdf",
        chapters=[
            {
                "id": "c0001",
                "number": 1,
                "title": "Part One",
                "start_block": 0,
                "end_block": 1,
                "confidence": 0.7,
                "generated_fingerprint": "a" * 64,
                "warnings": ["Chapter boundary has low confidence; verify manually"],
            }
        ],
    )
    write_manifest(path, manifest)
    restored = read_manifest(path)
    assert restored.chapters[0].generated_fingerprint == "a" * 64
    assert restored.chapters[0].warnings == ["Chapter boundary has low confidence; verify manually"]


def test_manifest_schema_version_is_required():
    with pytest.raises(ValueError):
        BookManifest.model_validate(
            {"input_sha256": "a" * 64, "title": "Test", "source_path": "book.pdf"}
        )


def test_atomic_write_and_stage_fingerprints(tmp_path: Path):
    path = tmp_path / "nested" / "payload.txt"
    atomic_write(path, b"first")
    assert path.read_bytes() == b"first"
    atomic_write(path, b"second")
    assert path.read_bytes() == b"second"
    assert list(path.parent.glob(".tmp-*")) == []
    assert fingerprint("text", {"voice": "Jasper", "speed": 1}) == fingerprint(
        "text", {"speed": 1, "voice": "Jasper"}
    )
    assert fingerprint("text", {"voice": "Jasper"}) != fingerprint("text", {"voice": "Bella"})
