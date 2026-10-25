"""The review gate follows the manifest as it is now, and only the user clears damage (R73)."""

import json

import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.config import Settings
from pdf2audiobook.errors import AudioError
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock
from pdf2audiobook.pipeline import convert_book
from pdf2audiobook.review_ui import _review_payload, save_chapter_updates
from pdf2audiobook.workspace import read_manifest, write_manifest

runner = CliRunner()


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


def test_changed_damaged_source_warning_wording_keeps_structured_gate(tmp_path, monkeypatch):
    import pymupdf as fitz

    from pdf2audiobook import pipeline
    from pdf2audiobook.pdf import ExtractedDocument

    source = tmp_path / "book.pdf"
    with fitz.open() as document:
        document.new_page()
        document.save(source)
    extracted = ExtractedDocument(
        title="Book",
        author=None,
        toc=[],
        spans=[],
        blocks=[DocumentBlock(id="b1", text="Narration.", page_index=0)],
        warnings=["A revised warning about source integrity"],
        page_sizes=[(600, 800)],
        review_reasons=["damaged_source"],
    )
    monkeypatch.setattr(pipeline, "extract_pdf", lambda *_a, **_k: extracted)
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "output")
    settings.chapters.allow_single_chapter = True
    manifest_path = pipeline.analyze_book(source, settings)
    assert "damaged_source" in read_manifest(manifest_path).review_required


def test_accept_empty_chapter_exits_2_without_workspace_changes(tmp_path, monkeypatch):
    source, path = _source_and_workspace(tmp_path)
    before = {item.relative_to(path.parent): item.read_bytes() for item in path.parent.rglob("*")}
    called = []
    monkeypatch.setattr(
        "pdf2audiobook.pipeline.analyze_book", lambda *_a, **_k: called.append(True) or path
    )
    result = runner.invoke(
        app,
        [
            "convert",
            str(source),
            "--no-config",
            "--output",
            str(path.parent),
            "--accept-review",
            "empty_chapter",
        ],
    )
    assert result.exit_code == 2
    assert " ".join(result.stderr.split()) == (
        "Error: empty_chapter cannot be accepted globally; approve the chapter in the review UI"
    )
    assert called == []
    after = {item.relative_to(path.parent): item.read_bytes() for item in path.parent.rglob("*")}
    assert after == before


def test_stale_empty_acknowledgement_is_ignored_and_warned(tmp_path, monkeypatch):
    manifest = _manifest(review_acknowledged=["empty_chapter"])
    manifest.blocks[1].text = "* * *"
    path = _workspace(tmp_path, manifest)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"synthetic")
    monkeypatch.setattr("pdf2audiobook.pipeline.analyze_book", lambda *_a, **_k: path)
    events = []
    monkeypatch.setattr(
        "pdf2audiobook.pipeline.log_event", lambda *args, **kwargs: events.append((args, kwargs))
    )
    with pytest.raises(AudioError, match="Chapter 2 has no speakable text"):
        convert_book(source, Settings(), chapter=2)
    assert read_manifest(path).review_acknowledged == ["empty_chapter"]
    assert any(
        args[0] == "review_warning" and kwargs.get("reason") == "empty_chapter_requires_approval"
        for args, kwargs in events
    )


def test_approval_skips_only_that_empty_chapter(tmp_path, monkeypatch):
    manifest = _manifest(review_acknowledged=["empty_chapter"])
    manifest.chapters[1].manually_approved = True
    manifest.blocks[1].text = "* * *"
    path = _workspace(tmp_path, manifest)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"synthetic")
    monkeypatch.setattr("pdf2audiobook.pipeline.analyze_book", lambda *_a, **_k: path)
    assert convert_book(source, Settings(), chapter=2) == []
    status = json.loads((path.parent / "reports" / "conversion_status.json").read_text())
    assert status["chapters"][0]["number"] == 2
    assert status["chapters"][0]["status"] == "skipped"

    saved = read_manifest(path)
    saved.blocks.append(DocumentBlock(id="b3", text="* * *", page_index=0))
    saved.chapters.append(
        Chapter(id="c3", number=3, title="Three", start_block=2, end_block=3, confidence=1)
    )
    write_manifest(path, saved)
    with pytest.raises(AudioError, match="Chapter 3 has no speakable text"):
        convert_book(source, Settings(), chapter=3)


def _source_and_workspace(tmp_path):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"synthetic")
    path = _workspace(tmp_path, _manifest())
    return source, path
