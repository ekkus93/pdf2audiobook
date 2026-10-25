"""Inspect reports persistent failed chapter status alongside the manifest."""

import json

from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock
from pdf2audiobook.workspace import write_manifest


def test_inspect_json_includes_failed_chapter_report(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    write_manifest(
        manifest_path,
        BookManifest(
            schema_version=3,
            input_sha256="a" * 64,
            title="Synthetic",
            source_path="book.pdf",
            blocks=[DocumentBlock(id="b1", page_index=0, text="Text.")],
            chapters=[
                Chapter(id="c1", number=1, title="One", start_block=0, end_block=1, confidence=1)
            ],
        ),
    )
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "conversion_status.json").write_text(
        json.dumps({"chapters": [{"number": 1, "status": "failed", "error_code": 7}]}),
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["inspect", str(manifest_path), "--json"])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["conversion_status"]["chapters"][0]["status"] == "failed"
