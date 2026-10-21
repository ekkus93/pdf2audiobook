import json
from pathlib import Path

import pytest

from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.models import BookManifest
from pdf2audiobook.workspace import atomic_write, fingerprint, read_manifest, write_manifest


def test_manifest_schema_version_is_rejected(tmp_path: Path):
    path = tmp_path / "manifest.json"
    manifest = BookManifest(input_sha256="a" * 64, title="Test", source_path="input.pdf")
    write_manifest(path, manifest)
    assert read_manifest(path).schema_version == 1
    data = json.loads(path.read_text())
    data["schema_version"] = 999
    path.write_text(json.dumps(data))
    with pytest.raises(ExtractionError, match="Cannot read or validate audiobook manifest") as exc:
        read_manifest(path)
    assert exc.value.__suppress_context__ is True
    assert path.read_text(encoding="utf-8") == json.dumps(data)


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
    assert fingerprint("text", {"voice": "Jasper"}) != fingerprint(
        "text", {"voice": "Bella"}
    )
