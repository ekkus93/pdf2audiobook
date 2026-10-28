"""Review fixes for the `edits` commands (Q1-Q4)."""

import json
from pathlib import Path

from test_edit_review import SECRET, _edit, _run, _workspace

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


def _mixed_workspace(tmp_path: Path) -> Path:
    return _workspace(
        tmp_path,
        [
            _edit("a1", "Alpha teh first.", "Alpha the first.", "deterministic", True),
            _edit("a2", "Alpha second block.", "Alpha 2nd block.", "deterministic", False),
            _edit("b1", "Beta teh opening.", "Beta the opening."),
            _edit("b2", "Beta closing block.", "Beta final block."),
        ],
    )


def _ids(path: Path, status: str) -> list[str]:
    out = _run("list", str(path), "--status", status, "--json")
    assert out.exit_code == 0, out.stderr
    return [e["block_id"] for e in json.loads(out.stdout)["edits"]]


def test_a_rejected_builtin_edit_is_listed_as_rejected_not_pending(tmp_path: Path) -> None:
    path = _mixed_workspace(tmp_path)
    assert _ids(path, "pending") == ["b1", "b2"]
    assert _ids(path, "rejected") == ["a2"]
    assert _ids(path, "accepted") == ["a1"]
    assert _ids(path, "all") == ["a1", "a2", "b1", "b2"]


def _decisions(path: Path) -> dict[str, bool]:
    return {e.block_id: e.accepted for e in read_manifest(path).edits}


def test_accept_all_leaves_a_rejected_builtin_edit_alone(tmp_path: Path) -> None:
    path = _mixed_workspace(tmp_path)
    assert _run("accept", str(path), "--all").exit_code == 0
    assert _decisions(path) == {"a1": True, "a2": False, "b1": True, "b2": True}


def test_reject_all_removes_only_pending_edits(tmp_path: Path) -> None:
    path = _mixed_workspace(tmp_path)
    assert _run("reject", str(path), "--all").exit_code == 0
    assert _decisions(path) == {"a1": True, "a2": False}


def test_naming_a_rejected_builtin_edit_is_a_content_free_usage_error(tmp_path: Path) -> None:
    path = _mixed_workspace(tmp_path)
    before = path.read_bytes()
    for verb in ("accept", "reject"):
        result = _run(verb, str(path), "a2")
        assert result.exit_code == 2
        assert "rejected during review" in result.stderr
        assert SECRET not in result.stdout + result.stderr
    assert path.read_bytes() == before
