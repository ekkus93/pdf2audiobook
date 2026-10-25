"""Untrusted manifests must never leak book text or private workspace paths."""

import json

import pytest

from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.models import BookManifest
from pdf2audiobook.workspace import read_manifest, write_manifest


@pytest.mark.parametrize(
    "payload",
    [
        b'{"title":"PRIVATE_BOOK_TEXT", bad-json',
        b'{"schema_version":99,"input_sha256":"abc","title":"PRIVATE_BOOK_TEXT","source_path":"private.pdf"}',
        b'{"schema_version":1,"input_sha256":"abc","title":"PRIVATE_BOOK_TEXT","source_path":"private.pdf"}',
        b'{"schema_version":2,"input_sha256":"abc","title":"PRIVATE_BOOK_TEXT","source_path":"private.pdf"}',
        b'{"input_sha256":"abc","title":"PRIVATE_BOOK_TEXT","source_path":"private.pdf"}',
        b'{"title":"PRIVATE_BOOK_TEXT","source_path":"private.pdf","chapters":[{"id":"chapter","number":0,"title":"PRIVATE_BOOK_TEXT","start_block":0,"end_block":1,"confidence":1.0}]}',
        b"\\xff\\xfePRIVATE_BOOK_TEXT",
    ],
)
def test_untrusted_manifest_failures_are_content_free(tmp_path, payload):
    private = tmp_path / "PRIVATE_WORKSPACE_PATH" / "manifest.json"
    private.parent.mkdir()
    private.write_bytes(payload)
    original = private.read_bytes()

    with pytest.raises(ExtractionError, match="Cannot read or validate audiobook manifest") as info:
        read_manifest(private)

    assert info.value.__suppress_context__
    for secret in ("PRIVATE_BOOK_TEXT", "PRIVATE_WORKSPACE_PATH"):
        assert secret not in str(info.value)
    assert private.read_bytes() == original


def test_missing_manifest_does_not_leak_path(tmp_path):
    private = tmp_path / "PRIVATE_WORKSPACE_PATH" / "missing.json"
    with pytest.raises(ExtractionError, match="Cannot read or validate audiobook manifest") as info:
        read_manifest(private)
    assert info.value.__suppress_context__
    assert "PRIVATE_WORKSPACE_PATH" not in str(info.value)


def test_valid_manifest_round_trip_is_unchanged(tmp_path):
    path = tmp_path / "manifest.json"
    manifest = BookManifest(
        schema_version=3, input_sha256="a" * 64, title="Ordinary book", source_path="ordinary.pdf"
    )
    write_manifest(path, manifest)
    assert read_manifest(path) == manifest
    assert json.loads(path.read_text(encoding="utf-8"))["title"] == "Ordinary book"
