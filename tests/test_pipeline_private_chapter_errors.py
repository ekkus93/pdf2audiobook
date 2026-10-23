"""Broken approved chapter text must fail before voice synthesis without leaking paths."""

import pytest

from pdf2audiobook import pipeline
from pdf2audiobook.config import Settings
from pdf2audiobook.errors import AudioError
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock


@pytest.mark.parametrize("failure", ["missing", "invalid_encoding"])
def test_missing_or_undecodable_chapter_text_is_private(tmp_path, monkeypatch, failure):
    source = tmp_path / "PRIVATE_BOOK_TITLE.pdf"
    source.write_bytes(b"synthetic PDF placeholder")
    root = tmp_path / "workspace-PRIVATE_BOOK_TITLE"
    manifest_path = root / "manifest.json"
    chapter = Chapter(
        id="chapter-one",
        number=1,
        title="Private synthetic chapter",
        start_block=0,
        end_block=1,
        confidence=1.0,
    )
    manifest = BookManifest(
        input_sha256="synthetic-input",
        title="Synthetic book",
        source_path=str(source),
        blocks=[
            DocumentBlock(
                id="body",
                page_index=0,
                text="Synthetic words",
                span_ids=[],
            )
        ],
        chapters=[chapter],
    )
    if failure == "invalid_encoding":
        folder = root / "chapters"
        folder.mkdir(parents=True)
        (folder / "001.txt").write_bytes(bytes([0xFF, 0xFE]))

    settings = Settings()
    monkeypatch.setattr(pipeline, "analyze_book", lambda *args, **_kw: manifest_path)
    monkeypatch.setattr(pipeline, "read_manifest", lambda _path: manifest)
    monkeypatch.setattr(pipeline, "render_chapter_texts", lambda *args: None)
    monkeypatch.setattr(
        pipeline,
        "KittenProvider",
        lambda *_args: pytest.fail("Kitten model must not load on invalid chapter text"),
    )

    with pytest.raises(AudioError, match="Cannot read approved chapter text") as exc:
        pipeline.convert_book(source, settings)
    assert exc.value.__suppress_context__ is True
    assert "PRIVATE_BOOK_TITLE" not in str(exc.value)
    assert not (root / "audio").exists()
