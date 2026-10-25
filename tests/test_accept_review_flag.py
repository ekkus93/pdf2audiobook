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
