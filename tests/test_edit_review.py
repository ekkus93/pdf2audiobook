"""Pending LLM edits are accepted or rejected explicitly, and only then reach the text (C4)."""

import fcntl
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pdf2audiobook import review_transaction
from pdf2audiobook.cli import app
from pdf2audiobook.document.structure import render_chapter_texts
from pdf2audiobook.models import BookManifest, Chapter, CleanupEdit, DocumentBlock
from pdf2audiobook.review_transaction import JOURNAL, ReviewRecoveryRequired
from pdf2audiobook.workspace import read_manifest, write_manifest

SECRET = "SecretBookSentence"


def _edit(
    block_id: str,
    original: str,
    replacement: str,
    provider: str = "llm",
    accepted: bool = False,
) -> CleanupEdit:
    return CleanupEdit(
        block_id=block_id,
        original=original,
        replacement=replacement,
        reason=f"model said {SECRET}",
        confidence=0.9,
        accepted=accepted,
        provider=provider,
    )


def _workspace(tmp_path: Path, edits: list[CleanupEdit] | None = None) -> Path:
    blocks = [
        DocumentBlock(id="a1", page_index=0, text="Alpha teh first."),
        DocumentBlock(id="a2", page_index=0, text="Alpha second block."),
        DocumentBlock(id="b1", page_index=1, text="Beta teh opening."),
        DocumentBlock(id="b2", page_index=1, text="Beta closing block."),
    ]
    manifest = BookManifest(
        schema_version=3,
        input_sha256="x",
        title="Book",
        source_path="source",
        blocks=blocks,
        chapters=[
            Chapter(id="c1", number=1, title="One", start_block=0, end_block=2, confidence=1),
            Chapter(id="c2", number=2, title="Two", start_block=2, end_block=4, confidence=1),
        ],
        edits=edits
        if edits is not None
        else [
            _edit("a1", "Alpha teh first.", "Alpha the first."),
            _edit("b1", "Beta teh opening.", "Beta the opening."),
        ],
    )
    path = tmp_path / "manifest.json"
    write_manifest(path, manifest)
    render_chapter_texts(manifest, tmp_path)
    return path


def _run(*args: str):
    return CliRunner().invoke(app, ["edits", *args])


def _text(folder: Path, number: int) -> str:
    return (folder / "chapters" / f"{number:03d}.txt").read_text(encoding="utf-8")


def _snapshot(folder: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(folder)): p.read_bytes()
        for p in sorted(folder.rglob("*"))
        if p.is_file() and p.name != ".convert.lock"
    }


def test_list_defaults_to_pending_and_json_holds_no_book_text(tmp_path: Path) -> None:
    path = _workspace(tmp_path)
    result = _run("list", str(path), "--json")
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert [(e["block_id"], e["chapter"], e["status"]) for e in payload["edits"]] == [
        ("a1", 1, "pending"),
        ("b1", 2, "pending"),
    ]
    assert all(e["provider"] == "llm" for e in payload["edits"])
    assert SECRET not in result.stdout and "teh" not in result.stdout


def test_human_list_shows_the_original_and_proposed_text(tmp_path: Path) -> None:
    path = _workspace(tmp_path)
    result = _run("list", str(path))
    assert result.exit_code == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "Alpha teh first." in combined and "Alpha the first." in combined


def test_list_filters_by_status(tmp_path: Path) -> None:
    path = _workspace(tmp_path)
    assert _run("accept", str(path), "a1").exit_code == 0

    def ids(status: str) -> list[str]:
        out = _run("list", str(path), "--status", status, "--json")
        return [e["block_id"] for e in json.loads(out.stdout)["edits"]]

    assert ids("pending") == ["b1"]
    assert ids("accepted") == ["a1"]
    assert ids("all") == ["a1", "b1"]


def test_accept_changes_exactly_that_blocks_text(tmp_path: Path) -> None:
    path = _workspace(tmp_path)
    second = _text(tmp_path, 2)
    result = _run("accept", str(path), "a1", "--json")
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["accepted"] == ["a1"]
    assert "Alpha the first." in _text(tmp_path, 1) and "teh" not in _text(tmp_path, 1)
    assert _text(tmp_path, 2) == second  # the other chapter is untouched
    edits = {e.block_id: e.accepted for e in read_manifest(path).edits}
    assert edits == {"a1": True, "b1": False}


def test_accepting_twice_is_harmless(tmp_path: Path) -> None:
    path = _workspace(tmp_path)
    assert _run("accept", str(path), "a1").exit_code == 0
    before = _snapshot(tmp_path)
    again = _run("accept", str(path), "a1", "--json")
    assert again.exit_code == 0, again.stderr
    assert json.loads(again.stdout)["accepted"] == []
    assert _snapshot(tmp_path) == before


def test_all_accepts_every_pending_edit(tmp_path: Path) -> None:
    path = _workspace(tmp_path)
    result = _run("accept", str(path), "--all", "--json")
    assert json.loads(result.stdout)["accepted"] == ["a1", "b1"]
    assert "the first" in _text(tmp_path, 1) and "the opening" in _text(tmp_path, 2)


def test_a_hand_edited_chapter_is_a_conflict_and_nothing_changes(tmp_path: Path) -> None:
    path = _workspace(tmp_path)
    (tmp_path / "chapters" / "001.txt").write_text("My own narration.\n", encoding="utf-8")
    render_chapter_texts(read_manifest(path), tmp_path)  # the edit is observed and recorded
    before = _snapshot(tmp_path)
    result = _run("accept", str(path), "a1")
    assert result.exit_code == 4
    assert "Chapter 1 text conflicts" in result.stderr
    assert "My own narration" not in result.stderr and str(tmp_path) not in result.stderr
    assert _snapshot(tmp_path) == before


def test_an_interrupted_accept_is_recovered_by_the_recover_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _workspace(tmp_path)
    original = review_transaction.atomic_write

    def fail_manifest(target: Path, data: bytes) -> None:
        if target == path:
            raise OSError("failure")
        original(target, data)

    with monkeypatch.context() as patch:
        patch.setattr(review_transaction, "atomic_write", fail_manifest)
        with pytest.raises(ReviewRecoveryRequired):
            from pdf2audiobook.edit_review import accept_edits

            accept_edits(path, ["a1"])
    assert (tmp_path / JOURNAL).exists()
    recovered = CliRunner().invoke(app, ["recover", str(path), "--json"])
    assert recovered.exit_code == 0, recovered.stderr
    assert {e.block_id: e.accepted for e in read_manifest(path).edits}["a1"] is True
    assert "Alpha the first." in _text(tmp_path, 1)


def test_lock_contention_returns_the_lock_error(tmp_path: Path) -> None:
    path = _workspace(tmp_path)
    with (tmp_path / ".convert.lock").open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        accepted = _run("accept", str(path), "a1")
        rejected = _run("reject", str(path), "a1")
    assert accepted.exit_code == 6 and rejected.exit_code == 6
    assert "already running" in accepted.stderr


def test_unknown_and_ambiguous_block_ids_are_usage_errors(tmp_path: Path) -> None:
    both = [
        _edit("a1", "Alpha teh first.", "Alpha the first."),
        _edit("a1", "Alpha teh first.", "Alpha a different first."),
    ]
    path = _workspace(tmp_path, both)
    before = _snapshot(tmp_path)
    unknown = _run("accept", str(path), "nope")
    assert unknown.exit_code == 2 and "nope" not in unknown.stderr
    ambiguous = _run("accept", str(path), "a1")
    assert ambiguous.exit_code == 2 and "More than one" in ambiguous.stderr
    assert _snapshot(tmp_path) == before


def test_arguments_must_name_blocks_or_all(tmp_path: Path) -> None:
    path = _workspace(tmp_path)
    assert _run("accept", str(path)).exit_code == 2
    assert _run("accept", str(path), "a1", "--all").exit_code == 2


def test_reject_removes_the_proposal_and_leaves_the_text_alone(tmp_path: Path) -> None:
    path = _workspace(tmp_path)
    chapters = {n: _text(tmp_path, n) for n in (1, 2)}
    result = _run("reject", str(path), "a1", "--json")
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["rejected"] == ["a1"]
    assert [e.block_id for e in read_manifest(path).edits] == ["b1"]
    assert {n: _text(tmp_path, n) for n in (1, 2)} == chapters


def test_reject_all_and_rejecting_an_accepted_edit(tmp_path: Path) -> None:
    path = _workspace(tmp_path)
    assert _run("accept", str(path), "a1").exit_code == 0
    refused = _run("reject", str(path), "a1")
    assert refused.exit_code == 2 and "already accepted" in refused.stderr
    assert json.loads(_run("reject", str(path), "--all", "--json").stdout)["rejected"] == ["b1"]
    assert [e.block_id for e in read_manifest(path).edits] == ["a1"]


def test_decisions_are_audited_without_book_text(tmp_path: Path) -> None:
    path = _workspace(tmp_path)
    _run("accept", str(path), "a1")
    _run("reject", str(path), "b1")
    audit = json.loads((tmp_path / "reports" / "edit_decisions.json").read_text())
    assert [(d["block_id"], d["action"]) for d in audit["decisions"]] == [
        ("a1", "accepted"),
        ("b1", "rejected"),
    ]
    assert SECRET not in json.dumps(audit) and "teh" not in json.dumps(audit)


def test_an_unaccepted_deterministic_edit_is_a_rejection_that_accept_leaves_alone(
    tmp_path: Path,
) -> None:
    path = _workspace(
        tmp_path, [_edit("a1", "Alpha teh first.", "Alpha the first.", provider="deterministic")]
    )
    listed = json.loads(_run("list", str(path), "--status", "rejected", "--json").stdout)["edits"]
    assert listed[0]["provider"] == "deterministic" and listed[0]["status"] == "rejected"
    assert _run("accept", str(path), "--all").exit_code == 0
    assert "Alpha teh first." in _text(tmp_path, 1)
