"""`edits list --json --with-text` adds the edit text, only on request (Tauri spec D4.6)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.models import BookManifest, Chapter, CleanupEdit, DocumentBlock
from pdf2audiobook.workspace import write_manifest

runner = CliRunner()
SECRET = "PRIVATE_EDIT_TEXT_42"


def _manifest(tmp_path: Path) -> Path:
    path = tmp_path / "manifest.json"
    write_manifest(
        path,
        BookManifest(
            schema_version=3,
            input_sha256="x",
            title="Book",
            source_path="source.pdf",
            blocks=[DocumentBlock(id="b0", text=f"Teh {SECRET}.", page_index=0)],
            chapters=[
                Chapter(id="a", number=1, title="One", start_block=0, end_block=1, confidence=1)
            ],
            edits=[
                CleanupEdit(
                    block_id="b0",
                    original=f"Teh {SECRET}.",
                    replacement=f"The {SECRET}.",
                    reason=f"spelling near {SECRET}",
                    confidence=0.9,
                    accepted=False,
                    provider="ollama",
                )
            ],
        ),
    )
    return path


def test_without_the_flag_json_carries_no_book_text(tmp_path: Path) -> None:
    result = runner.invoke(app, ["edits", "list", str(_manifest(tmp_path)), "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["edits"] == [
        {"block_id": "b0", "chapter": 1, "provider": "ollama", "status": "pending"}
    ]
    assert SECRET not in result.stdout


def test_with_the_flag_json_carries_the_text_and_reason(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["edits", "list", str(_manifest(tmp_path)), "--json", "--with-text"]
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["edits"] == [
        {
            "block_id": "b0",
            "chapter": 1,
            "provider": "ollama",
            "status": "pending",
            "reason": f"spelling near {SECRET}",
            "original": f"Teh {SECRET}.",
            "replacement": f"The {SECRET}.",
        }
    ]
