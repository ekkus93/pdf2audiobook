"""Review fixes for the `edits` commands (Q1-Q4)."""

import json
from pathlib import Path

import pytest
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


def _snapshot(folder: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(folder)): p.read_bytes()
        for p in sorted(folder.rglob("*"))
        if p.is_file() and p.name != ".convert.lock"
    }


def _doubled_workspace(tmp_path: Path) -> Path:
    """Block a1 already carries an accepted edit; a second one is pending. b2 is clean."""
    return _workspace(
        tmp_path,
        [
            _edit("a1", "Alpha teh first.", "Alpha the first.", "deterministic", True),
            _edit("a1", "Alpha teh first.", "Alpha first, read aloud."),
            _edit("b2", "Beta closing block.", "Beta final block."),
        ],
    )


def test_accepting_a_second_edit_on_a_block_is_refused_by_id_and_by_all(tmp_path: Path) -> None:
    path = _doubled_workspace(tmp_path)
    before = _snapshot(tmp_path)
    for args in (("a1",), ("--all",)):
        result = _run("accept", str(path), *args)
        assert result.exit_code == 2, args
        assert "already has an accepted edit" in result.stderr
        assert "a1" in result.stderr
        assert SECRET not in result.stdout + result.stderr
        assert _snapshot(tmp_path) == before  # all-or-nothing: b2 was not accepted either


def test_two_pending_edits_on_one_block_refuse_accept_all(tmp_path: Path) -> None:
    path = _workspace(
        tmp_path,
        [
            _edit("b1", "Beta teh opening.", "Beta the opening."),
            _edit("b1", "Beta teh opening.", "Beta opening, spoken."),
        ],
    )
    before = _snapshot(tmp_path)
    result = _run("accept", str(path), "--all")
    assert result.exit_code == 2
    assert "More than one pending edit targets block b1" in result.stderr
    assert _snapshot(tmp_path) == before


def test_a_single_pending_edit_on_a_block_still_accepts(tmp_path: Path) -> None:
    path = _workspace(
        tmp_path,
        [
            _edit("b1", "Beta teh opening.", "Beta the opening."),
            _edit("b1", "Beta teh opening.", "Beta opening, spoken."),
        ],
    )
    # Control: with only one proposal left the same block accepts normally.
    manifest = read_manifest(path)
    manifest.edits = manifest.edits[:1]
    write_manifest(path, manifest)
    assert _run("accept", str(path), "--all").exit_code == 0


def _failing_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(path: object, data: object) -> None:
        raise OSError(f"disk exploded near {SECRET} at {path}")

    monkeypatch.setattr("pdf2audiobook.edit_review.write_json", refuse)


@pytest.mark.parametrize("verb", ["accept", "reject"])
def test_a_failed_audit_write_is_reported_but_the_decision_is_saved(
    verb: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _workspace(tmp_path)
    _failing_audit(monkeypatch)
    result = _run(verb, str(path), "--all")
    assert result.exit_code == 0, result.stderr
    assert "Could not update reports/edit_decisions.json; the decision itself was saved" in (
        result.stderr
    )
    for leak in (SECRET, "disk exploded", str(tmp_path)):
        assert leak not in result.stdout + result.stderr
    edits = read_manifest(path).edits
    assert (len(edits) == 0) if verb == "reject" else all(e.accepted for e in edits)


@pytest.mark.parametrize("verb", ["accept", "reject"])
def test_a_failed_audit_write_adds_a_json_warning_code(
    verb: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _workspace(tmp_path)
    _failing_audit(monkeypatch)
    result = _run(verb, str(path), "--all", "--json")
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["warnings"] == ["edit_audit_not_written"]
    assert SECRET not in result.stdout + result.stderr


def test_a_corrupt_audit_file_is_replaced(tmp_path: Path) -> None:
    path = _workspace(tmp_path)
    audit = tmp_path / "reports" / "edit_decisions.json"
    audit.parent.mkdir(parents=True, exist_ok=True)
    audit.write_text("{not json", encoding="utf-8")
    result = _run("accept", str(path), "--all", "--json")
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["warnings"] == []
    decisions = json.loads(audit.read_text(encoding="utf-8"))["decisions"]
    assert [d["block_id"] for d in decisions] == ["a1", "b1"]


def test_a_successful_audit_adds_no_warning(tmp_path: Path) -> None:
    result = _run("accept", str(_workspace(tmp_path)), "--all", "--json")
    assert json.loads(result.stdout)["warnings"] == []
