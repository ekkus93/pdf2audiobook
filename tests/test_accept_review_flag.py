"""`convert --accept-review` validates early, logs the acknowledgement and works in dry-run."""

import json

from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock
from pdf2audiobook.workspace import read_manifest, write_manifest

runner = CliRunner()


def _damaged_workspace(tmp_path):
    folder = tmp_path / "workspace"
    folder.mkdir()
    path = folder / "manifest.json"
    write_manifest(
        path,
        BookManifest(
            schema_version=3,
            input_sha256="x",
            title="Book",
            source_path="source.pdf",
            blocks=[DocumentBlock(id="b", text="Text.", page_index=0)],
            chapters=[
                Chapter(id="c", number=1, title="One", start_block=0, end_block=1, confidence=1)
            ],
            review_required=["damaged_source"],
        ),
    )
    source = tmp_path / "source.pdf"
    source.write_bytes(b"synthetic")
    return source, path


def test_unknown_reason_exits_2_before_any_analysis(tmp_path, monkeypatch):
    source, path = _damaged_workspace(tmp_path)
    called = []
    monkeypatch.setattr(
        "pdf2audiobook.pipeline.analyze_book", lambda *_a, **_k: called.append(1) or path
    )
    result = runner.invoke(
        app, ["convert", str(source), "--no-config", "--accept-review", "no_such_reason"]
    )
    assert result.exit_code == 2, result.stderr
    assert "Unknown --accept-review reason" in result.stderr
    assert called == []
    assert read_manifest(path).review_required == ["damaged_source"]


def test_acknowledgement_is_logged_without_content(tmp_path, monkeypatch):
    source, path = _damaged_workspace(tmp_path)
    monkeypatch.setattr("pdf2audiobook.pipeline.analyze_book", lambda *_a, **_k: path)
    monkeypatch.setattr("pdf2audiobook.pipeline.select_chapters", lambda *_a, **_k: [])
    result = runner.invoke(
        app,
        ["--verbose", "convert", str(source), "--no-config", "--accept-review", "damaged_source"],
    )
    assert result.exit_code == 0, result.stderr
    events = [json.loads(line) for line in result.stderr.splitlines() if '"event"' in line]
    assert {
        "event": "review_acknowledged",
        "fields": {"status": "damaged_source"},
        "level": "info",
    } in events
    assert "Text." not in result.stderr


def test_dry_run_applies_and_reports_the_acknowledgement(tmp_path, monkeypatch):
    source, path = _damaged_workspace(tmp_path)
    monkeypatch.setattr("pdf2audiobook.pipeline.analyze_book", lambda *_a, **_k: path)
    blocked = runner.invoke(app, ["convert", str(source), "--no-config", "--dry-run", "--json"])
    assert blocked.exit_code == 6
    allowed = runner.invoke(
        app,
        [
            "convert",
            str(source),
            "--no-config",
            "--dry-run",
            "--json",
            "--accept-review",
            "damaged_source",
        ],
    )
    assert allowed.exit_code == 0, allowed.stderr
    payload = json.loads(allowed.stdout)
    assert payload["would_acknowledge"] == ["damaged_source"]
    assert read_manifest(path).review_required == ["damaged_source"]


def test_dry_run_refuses_a_hand_emptied_chapter(tmp_path, monkeypatch):
    source, path = _damaged_workspace(tmp_path)
    manifest = read_manifest(path)
    manifest.blocks[0].text = "* * *"
    manifest.review_required = ["empty_chapter"]
    write_manifest(path, manifest)
    before = path.read_bytes()
    monkeypatch.setattr("pdf2audiobook.pipeline.analyze_book", lambda *_a, **_k: path)

    result = runner.invoke(
        app,
        ["convert", str(source), "--no-config", "--dry-run", "--output", str(path.parent)],
    )

    assert result.exit_code == 6
    assert "Chapter 1 has no speakable text" in result.stderr
    assert path.read_bytes() == before


def test_dry_run_reports_an_approved_empty_chapter_as_skipped(tmp_path, monkeypatch):
    source, path = _damaged_workspace(tmp_path)
    manifest = read_manifest(path)
    manifest.blocks[0].text = "* * *"
    manifest.review_required = ["empty_chapter"]
    manifest.chapters[0].manually_approved = True
    write_manifest(path, manifest)
    monkeypatch.setattr("pdf2audiobook.pipeline.analyze_book", lambda *_a, **_k: path)

    result = runner.invoke(
        app,
        [
            "convert",
            str(source),
            "--no-config",
            "--dry-run",
            "--output",
            str(path.parent),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["skipped_chapters"] == [1]
    assert payload["chapters"] == 0
    assert payload["mp3_files"] == []


def test_dry_run_logs_acknowledgement_without_writing(tmp_path, monkeypatch):
    source, path = _damaged_workspace(tmp_path)
    before = {
        item.relative_to(path.parent): item.read_bytes()
        for item in path.parent.rglob("*")
        if item.is_file()
    }
    monkeypatch.setattr("pdf2audiobook.pipeline.analyze_book", lambda *_a, **_k: path)

    result = runner.invoke(
        app,
        [
            "--verbose",
            "convert",
            str(source),
            "--no-config",
            "--dry-run",
            "--output",
            str(path.parent),
            "--json",
            "--accept-review",
            "damaged_source",
        ],
    )

    assert result.exit_code == 0, result.stderr
    events = [json.loads(line) for line in result.stderr.splitlines() if '"event"' in line]
    assert {
        "event": "review_acknowledged",
        "fields": {"status": "damaged_source"},
        "level": "info",
    } in events
    after = {
        item.relative_to(path.parent): item.read_bytes()
        for item in path.parent.rglob("*")
        if item.is_file()
    }
    assert after == before
    assert read_manifest(path).review_required == ["damaged_source"]


def test_cli_acknowledges_ambiguous_page_numbers_after_chapter_approval(tmp_path, monkeypatch):
    source, path = _damaged_workspace(tmp_path)
    manifest = read_manifest(path)
    manifest.review_required = ["ambiguous_page_numbers"]
    for chapter in manifest.chapters:
        chapter.manually_approved = True
    write_manifest(path, manifest)
    monkeypatch.setattr("pdf2audiobook.pipeline.analyze_book", lambda *_a, **_k: path)

    blocked = runner.invoke(
        app,
        [
            "convert",
            str(source),
            "--no-config",
            "--output",
            str(path.parent),
            "--dry-run",
            "--json",
        ],
    )
    assert blocked.exit_code == 6

    allowed = runner.invoke(
        app,
        [
            "convert",
            str(source),
            "--no-config",
            "--output",
            str(path.parent),
            "--dry-run",
            "--json",
            "--accept-review",
            "ambiguous_page_numbers",
        ],
    )
    assert allowed.exit_code == 0, allowed.stderr
    assert json.loads(allowed.stdout)["would_acknowledge"] == ["ambiguous_page_numbers"]
    assert read_manifest(path).review_required == ["ambiguous_page_numbers"]
