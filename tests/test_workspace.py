import pytest

from pdf2audiobook.models import BookManifest, Chapter
from pdf2audiobook.workspace import atomic_write, fingerprint, read_manifest, write_manifest


def test_manifest(tmp_path):
    path = tmp_path / "manifest.json"
    book = BookManifest(
        schema_version=2, input_sha256="a" * 64, title="Test", source_path="book.pdf"
    )
    write_manifest(path, book)
    assert read_manifest(path) == book
    atomic_write(path, b"hello")
    assert path.read_bytes() == b"hello"


def test_schema_validation():
    with pytest.raises(ValueError):
        BookManifest(schema_version=99, input_sha256="x", title="Test", source_path="x")
    with pytest.raises(ValueError):
        Chapter(id="a", number=1, title="A", start_block=2, end_block=2, confidence=1.0)


def test_stable_cache_key():
    assert fingerprint({"x": 1, "y": 2}) == fingerprint({"y": 2, "x": 1})
