"""The review gate follows the manifest as it is now, and only the user clears damage (R73)."""

import json

import pytest

from pdf2audiobook.config import Settings
from pdf2audiobook.errors import AudioError
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock
from pdf2audiobook.pipeline import convert_book
from pdf2audiobook.review_ui import _review_payload, save_chapter_updates
from pdf2audiobook.workspace import read_manifest, write_manifest


def _manifest(**kwargs):
    return BookManifest(
        schema_version=3,
        input_sha256="x",
        title="Book",
        source_path="source.pdf",
        blocks=[
            DocumentBlock(id="b1", text="Narration one.", page_index=0),
            DocumentBlock(id="b2", text="Narration two.", page_index=0),
        ],
        chapters=[
            Chapter(id="c1", number=1, title="One", start_block=0, end_block=1, confidence=1),
            Chapter(id="c2", number=2, title="Two", start_block=1, end_block=2, confidence=1),
        ],
        **kwargs,
    )


def _workspace(tmp_path, manifest):
    folder = tmp_path / "workspace"
    folder.mkdir()
    path = folder / "manifest.json"
    write_manifest(path, manifest)
    return path


def test_chapter_emptied_after_analysis_is_gated_at_convert(tmp_path, monkeypatch):
    manifest = _manifest()
    path = _workspace(tmp_path, manifest)
    assert manifest.review_required == []
    # A hand edit empties chapter 2 after analysis had found nothing wrong.
    stored = json.loads(path.read_text())
    stored["blocks"][1]["text"] = "* * *"
    path.write_text(json.dumps(stored))
    source = tmp_path / "source.pdf"
    source.write_bytes(b"synthetic")
    monkeypatch.setattr("pdf2audiobook.pipeline.analyze_book", lambda *_a, **_k: path)
    with pytest.raises(AudioError, match="Chapter 2 has no speakable text"):
        convert_book(source, Settings())
    assert "empty_chapter" in read_manifest(path).review_required


def test_reason_is_dropped_when_the_chapter_is_fixed(tmp_path, monkeypatch):
    manifest = _manifest(review_required=["empty_chapter"])
    path = _workspace(tmp_path, manifest)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"synthetic")
    monkeypatch.setattr("pdf2audiobook.pipeline.analyze_book", lambda *_a, **_k: path)
    monkeypatch.setattr("pdf2audiobook.pipeline.select_chapters", lambda *_a, **_k: [])
    convert_book(source, Settings())
    assert read_manifest(path).review_required == []


def _updates(manifest, **extra):
    return [
        {
            "id": chapter.id,
            "title": chapter.title,
            "start_block": chapter.start_block,
            "end_block": chapter.end_block,
            **extra,
        }
        for chapter in manifest.chapters
    ]


def test_title_only_review_save_keeps_damaged_source(tmp_path):
    manifest = _manifest(review_required=["damaged_source"])
    path = _workspace(tmp_path, manifest)
    updates = _updates(manifest)
    updates[0]["title"] = "Renamed"
    save_chapter_updates(path, updates)
    saved = read_manifest(path)
    assert saved.review_required == ["damaged_source"]
    assert saved.review_acknowledged == []
    assert saved.chapters[0].title == "Renamed"


def test_explicit_acknowledgement_clears_damaged_source(tmp_path):
    manifest = _manifest(review_required=["damaged_source"])
    path = _workspace(tmp_path, manifest)
    save_chapter_updates(path, _updates(manifest), ["damaged_source"])
    saved = read_manifest(path)
    assert saved.review_required == []
    assert saved.review_acknowledged == ["damaged_source"]


def test_unknown_acknowledgement_is_rejected(tmp_path):
    manifest = _manifest(review_required=["damaged_source"])
    path = _workspace(tmp_path, manifest)
    with pytest.raises(Exception, match="acknowledgement"):
        save_chapter_updates(path, _updates(manifest), ["empty_chapter"])
    assert read_manifest(path).review_required == ["damaged_source"]


def test_review_page_offers_the_acknowledgement_only_for_damaged_sources():
    manifest = _manifest(review_required=["damaged_source"])
    assert _review_payload(manifest)["review_required"] == ["damaged_source"]
    assert _review_payload(_manifest())["review_required"] == []
