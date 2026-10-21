"""Chapter text resume compares existing artifacts without unbounded reads."""

from pathlib import Path

from pdf2audiobook.document import structure
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock
from pdf2audiobook import workspace


def test_render_chapter_texts_streams_existing_artifact_comparison(tmp_path, monkeypatch):
    text = "Synthetic long paragraph. " * 60000
    block = DocumentBlock(id="body", page_index=0, text=text, kind="paragraph")
    chapter = Chapter(
        id="chapter-one", number=1, title="Chapter One",
        start_block=0, end_block=1, confidence=1.0,
    )
    manifest = BookManifest(
        input_sha256="synthetic", title="Synthetic", source_path="synthetic.pdf",
        blocks=[block], chapters=[chapter],
    )
    chapter_path = tmp_path / "chapters" / "001.txt"
    structure.render_chapter_texts(manifest, tmp_path)
    expected = chapter_path.read_bytes()

    original_read_bytes = Path.read_bytes

    def forbid_full_chapter_read(self):
        if self == chapter_path:
            raise AssertionError("Chapter comparison must not call read_bytes()")
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", forbid_full_chapter_read)
    writes = []
    original_atomic_write = workspace.atomic_write

    def record_write(path, data):
        writes.append(path)
        return original_atomic_write(path, data)

    monkeypatch.setattr(workspace, "atomic_write", record_write)
    structure.render_chapter_texts(manifest, tmp_path)
    assert chapter_path not in writes

    chapter_path.write_bytes(expected[:-1] + b"!")
    structure.render_chapter_texts(manifest, tmp_path)
    assert chapter_path in writes
    assert chapter_path.stat().st_size == len(expected)
    with chapter_path.open("rb") as restored:
        assert restored.read(128) == expected[:128]
        restored.seek(-128, 2)
        assert restored.read() == expected[-128:]
