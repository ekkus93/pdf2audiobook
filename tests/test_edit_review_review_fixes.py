"""Review fixes for the `edits` commands (Q1-Q4)."""

import json
from pathlib import Path

from test_edit_review import _edit, _run, _workspace

from pdf2audiobook.workspace import read_manifest, write_manifest

BRACKETS = "x[i] + y[/b] and [bold] with [13]"


def _bracket_workspace(tmp_path: Path) -> Path:
    path = _workspace(tmp_path, [])
    manifest = read_manifest(path)
    text = f"Alpha {BRACKETS}."
    manifest.blocks[0].text = text
    manifest.edits = [_edit("a1", text, f"Alpha {BRACKETS} spoken.")]
    write_manifest(path, manifest)
    return path


def test_book_text_with_brackets_lists_verbatim(tmp_path: Path) -> None:
    result = _run("list", str(_bracket_workspace(tmp_path)))
    assert result.exit_code == 0, result.stderr
    shown = result.stdout + result.stderr  # the human listing goes to stderr
    assert shown.count(BRACKETS) == 2  # was: and now:
    assert "1 edit(s)" in shown


def test_json_listing_is_unchanged_and_content_free(tmp_path: Path) -> None:
    result = _run("list", str(_bracket_workspace(tmp_path)), "--json")
    assert result.exit_code == 0
    assert "x[i]" not in result.stdout and "[13]" not in result.stdout
    assert json.loads(result.stdout)["edits"][0]["block_id"] == "a1"
