"""The recover and regenerate-chapter commands resolve stuck workspaces safely (R4, R5)."""

import fcntl
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pdf2audiobook import review_transaction
from pdf2audiobook.chapter_artifacts import find_chapter_conflicts
from pdf2audiobook.cli import app
from pdf2audiobook.document.structure import render_chapter_narration, render_chapter_texts
from pdf2audiobook.errors import ChapterConflictError, PendingRecoveryError
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock
from pdf2audiobook.review_transaction import JOURNAL, ReviewRecoveryRequired
from pdf2audiobook.review_ui import save_chapter_updates
from pdf2audiobook.workspace import backup_file, read_manifest, workspace_lock, write_manifest

EDIT = "PrivateHandEdit"


def _manifest() -> BookManifest:
    return BookManifest(
        schema_version=3,
        input_sha256="x",
        title="Book",
        source_path="source",
        blocks=[DocumentBlock(id=f"b{i}", page_index=0, text=f"Body {i}.") for i in range(3)],
        chapters=[
            Chapter(id="a", number=1, title="One", start_block=0, end_block=1, confidence=1),
            Chapter(id="b", number=2, title="Two", start_block=1, end_block=3, confidence=1),
        ],
    )


def _workspace(tmp_path: Path) -> tuple[Path, BookManifest]:
    manifest = _manifest()
    path = tmp_path / "manifest.json"
    write_manifest(path, manifest)
    render_chapter_texts(manifest, tmp_path)
    return path, manifest


def _updates(manifest: BookManifest, end: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [
        {
            "id": chapter.id,
            "title": chapter.title,
            "start_block": chapter.start_block,
            "end_block": chapter.end_block,
        }
        for chapter in manifest.chapters
    ]
    rows[0]["end_block"] = end
    rows[1]["start_block"] = end
    return rows


def _edited_and_observed(tmp_path: Path) -> tuple[Path, BookManifest]:
    path, manifest = _workspace(tmp_path)
    (tmp_path / "chapters" / "001.txt").write_text(EDIT, encoding="utf-8")
    render_chapter_texts(manifest, tmp_path)  # the edit is observed and recorded
    return path, manifest


def _with_moved_boundary(path: Path, manifest: BookManifest) -> BookManifest:
    moved = manifest.model_copy(deep=True)
    moved.chapters[0].end_block = 2
    moved.chapters[1].start_block = 2
    write_manifest(path, moved)
    return moved


def _pending_blocked_transaction(
    path: Path, manifest: BookManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Commit a review whose manifest publication fails, then change chapter 1 externally."""
    original = review_transaction.atomic_write

    def fail(target: Path, data: bytes) -> None:
        if target == path:
            raise OSError("failure")
        original(target, data)

    with monkeypatch.context() as patch:
        patch.setattr(review_transaction, "atomic_write", fail)
        with pytest.raises(ReviewRecoveryRequired):
            save_chapter_updates(path, _updates(manifest, 2))
    (path.parent / "chapters" / "001.txt").write_text(EDIT, encoding="utf-8")


def _run(*args: str) -> tuple[int, str, str]:
    result = CliRunner().invoke(app, list(args))
    return result.exit_code, result.stdout, result.stderr


def test_backup_never_overwrites_an_existing_backup(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("first", encoding="utf-8")
    one = backup_file(tmp_path, source, subdir="chapter-backups", stem="001", timestamp="T")
    source.write_text("second", encoding="utf-8")
    two = backup_file(tmp_path, source, subdir="chapter-backups", stem="001", timestamp="T")
    assert one != two
    assert (tmp_path / one).read_text() == "first"
    assert (tmp_path / two).read_text() == "second"


def test_backup_refuses_a_symlinked_backup_directory(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("text", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "chapter-backups").symlink_to(outside)
    with pytest.raises(Exception, match="Cannot write a backup copy"):
        backup_file(tmp_path, source, subdir="chapter-backups", stem="001")
    assert list(outside.iterdir()) == []


def test_recovery_error_names_the_blocking_chapter_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, manifest = _workspace(tmp_path)
    _pending_blocked_transaction(path, manifest, monkeypatch)
    with pytest.raises(PendingRecoveryError) as raised:
        with workspace_lock(tmp_path):
            pass
    message = str(raised.value)
    assert raised.value.labels == ("chapter 1",)
    assert "chapter 1" in message and "recover" in message
    assert EDIT not in message and str(tmp_path) not in message


def test_recover_without_flag_reports_the_block_and_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, manifest = _workspace(tmp_path)
    _pending_blocked_transaction(path, manifest, monkeypatch)
    before = (tmp_path / "chapters" / "001.txt").read_bytes()
    code, out, err = _run("recover", str(path), "--json")
    assert code == 4
    assert "chapter 1" in err
    assert EDIT not in out + err and str(tmp_path) not in out + err
    assert (tmp_path / JOURNAL).exists()
    assert (tmp_path / "chapters" / "001.txt").read_bytes() == before
    assert not (tmp_path / "chapter-backups").exists()


def test_recover_back_up_changed_keeps_the_edit_and_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, manifest = _workspace(tmp_path)
    _pending_blocked_transaction(path, manifest, monkeypatch)
    code, out, err = _run("recover", str(path), "--back-up-changed", "--json")
    assert code == 0, err
    payload = json.loads(out)
    assert payload["status"] == "recovered" and payload["backed_up"] == ["chapter 1"]
    assert EDIT not in out and str(tmp_path) not in out
    backups = list((tmp_path / "chapter-backups").iterdir())
    assert [item.read_text() for item in backups] == [EDIT]
    assert not (tmp_path / JOURNAL).exists()
    assert read_manifest(path).chapters[0].end_block == 2
    code, out, _ = _run("recover", str(path), "--json")
    assert code == 0 and json.loads(out)["status"] == "nothing_pending"


def test_recover_back_up_changed_keeps_a_changed_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, manifest = _workspace(tmp_path)
    original = review_transaction.atomic_write

    def fail(target: Path, data: bytes) -> None:
        if target.name == "001.txt":
            raise OSError("failure")
        original(target, data)

    with monkeypatch.context() as patch:
        patch.setattr(review_transaction, "atomic_write", fail)
        with pytest.raises(ReviewRecoveryRequired):
            save_chapter_updates(path, _updates(manifest, 2))
    changed = path.read_text() + "\n"
    path.write_text(changed, encoding="utf-8")
    code, out, err = _run("recover", str(path), "--back-up-changed", "--json")
    assert code == 0, err
    assert json.loads(out)["backed_up"] == ["manifest"]
    backups = list((tmp_path / "workspace-backups").iterdir())
    assert [item.read_text() for item in backups] == [changed]
    assert read_manifest(path).chapters[0].end_block == 2


@pytest.mark.parametrize("flag", [[], ["--back-up-changed"]])
def test_invalid_journal_is_refused_without_writes(tmp_path: Path, flag: list[str]) -> None:
    path, _ = _workspace(tmp_path)
    (tmp_path / JOURNAL).write_text('{"version": 9, "entries": []}', encoding="utf-8")
    before = sorted(item.name for item in tmp_path.rglob("*"))
    code, out, err = _run("recover", str(path), "--json", *flag)
    assert code == 4
    assert "invalid" in err and "backup" in err
    assert sorted(item.name for item in tmp_path.rglob("*")) == before
    assert (tmp_path / JOURNAL).exists()


def test_recover_reports_nothing_pending_on_a_clean_workspace(tmp_path: Path) -> None:
    path, _ = _workspace(tmp_path)
    code, out, _ = _run("recover", str(path), "--json")
    assert code == 0 and json.loads(out) == {
        "status": "nothing_pending",
        "backed_up": [],
        "warnings": [],
    }


@pytest.mark.parametrize("command", [["recover"], ["regenerate-chapter", "--chapter", "1"]])
def test_commands_report_lock_contention(tmp_path: Path, command: list[str]) -> None:
    path, _ = _workspace(tmp_path)
    with (tmp_path / ".convert.lock").open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        code, _, err = _run(command[0], str(path), *command[1:], "--json")
    assert code == 6
    assert "already running" in err


def test_regenerate_restores_an_observed_edited_chapter_that_was_deleted(tmp_path: Path) -> None:
    path, manifest = _edited_and_observed(tmp_path)
    (tmp_path / "chapters" / "001.txt").unlink()
    with pytest.raises(ChapterConflictError):
        render_chapter_texts(manifest, tmp_path)
    code, out, err = _run("regenerate-chapter", str(path), "--chapter", "1", "--json")
    assert code == 0, err
    payload = json.loads(out)
    assert payload["regenerated"] == [1] and payload["backed_up"] == []
    expected = render_chapter_narration(manifest, manifest.chapters[0], "warn")
    assert (tmp_path / "chapters" / "001.txt").read_text() == expected
    render_chapter_texts(manifest, tmp_path)  # planning no longer conflicts
    assert find_chapter_conflicts(manifest, tmp_path, "warn") == []


def test_regenerate_backs_up_an_edited_chapter_byte_for_byte(tmp_path: Path) -> None:
    path, manifest = _edited_and_observed(tmp_path)
    moved = _with_moved_boundary(path, manifest)
    with pytest.raises(ChapterConflictError):
        render_chapter_texts(moved, tmp_path)
    code, out, err = _run("regenerate-chapter", str(path), "--chapter", "1", "--json")
    assert code == 0, err
    payload = json.loads(out)
    assert payload["backed_up"] == [1]
    assert EDIT not in out and str(tmp_path) not in out
    backups = list((tmp_path / "chapter-backups").iterdir())
    assert [item.read_bytes() for item in backups] == [EDIT.encode()]
    expected = render_chapter_narration(moved, moved.chapters[0], "warn")
    assert (tmp_path / "chapters" / "001.txt").read_text() == expected
    render_chapter_texts(moved, tmp_path)


def test_second_regeneration_makes_no_new_backup(tmp_path: Path) -> None:
    path, manifest = _edited_and_observed(tmp_path)
    _with_moved_boundary(path, manifest)
    assert _run("regenerate-chapter", str(path), "--chapter", "1", "--json")[0] == 0
    code, out, _ = _run("regenerate-chapter", str(path), "--chapter", "1", "--json")
    assert code == 0 and json.loads(out)["backed_up"] == []
    assert len(list((tmp_path / "chapter-backups").iterdir())) == 1


def test_all_conflicts_regenerates_every_blocked_chapter(tmp_path: Path) -> None:
    path, manifest = _workspace(tmp_path)
    (tmp_path / "chapters" / "001.txt").write_text(EDIT, encoding="utf-8")
    (tmp_path / "chapters" / "002.txt").write_text(EDIT + "2", encoding="utf-8")
    render_chapter_texts(manifest, tmp_path)
    moved = _with_moved_boundary(path, manifest)
    assert find_chapter_conflicts(moved, tmp_path, "warn") == [1, 2]
    code, out, err = _run("regenerate-chapter", str(path), "--all-conflicts", "--json")
    assert code == 0, err
    payload = json.loads(out)
    assert payload["regenerated"] == [1, 2] and payload["backed_up"] == [1, 2]
    assert find_chapter_conflicts(moved, tmp_path, "warn") == []
    code, out, _ = _run("regenerate-chapter", str(path), "--all-conflicts", "--json")
    assert code == 0 and json.loads(out)["regenerated"] == []


def test_regenerate_does_not_touch_unselected_edited_chapters(tmp_path: Path) -> None:
    path, manifest = _workspace(tmp_path)
    (tmp_path / "chapters" / "002.txt").write_text(EDIT, encoding="utf-8")
    render_chapter_texts(manifest, tmp_path)
    moved = _with_moved_boundary(path, manifest)
    code, _, _ = _run("regenerate-chapter", str(path), "--chapter", "1", "--json")
    assert code == 4  # chapter 2 is still a conflict, so nothing is published
    assert (tmp_path / "chapters" / "002.txt").read_text() == EDIT
    assert find_chapter_conflicts(moved, tmp_path, "warn") == [2]


def test_regenerate_requires_exactly_one_selector(tmp_path: Path) -> None:
    path, _ = _workspace(tmp_path)
    assert _run("regenerate-chapter", str(path), "--json")[0] == 2
    assert _run("regenerate-chapter", str(path), "--chapter", "1", "--all-conflicts")[0] == 2


def test_regenerate_rejects_an_unknown_chapter_without_leaking(tmp_path: Path) -> None:
    path, _ = _workspace(tmp_path)
    code, out, err = _run("regenerate-chapter", str(path), "--chapter", "9", "--json")
    assert code == 4 and "Chapter 9 does not exist" in err
    assert str(tmp_path) not in out + err


def test_interrupted_regeneration_recovers_with_the_recover_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, manifest = _edited_and_observed(tmp_path)
    moved = _with_moved_boundary(path, manifest)
    original = review_transaction.atomic_write

    def fail(target: Path, data: bytes) -> None:
        if target.name == "001.txt":
            raise OSError("failure")
        original(target, data)

    with monkeypatch.context() as patch:
        patch.setattr(review_transaction, "atomic_write", fail)
        code, _, err = _run("regenerate-chapter", str(path), "--chapter", "1", "--json")
    assert code == 4 and "committed" in err
    assert (tmp_path / JOURNAL).exists()
    code, out, _ = _run("recover", str(path), "--json")
    assert code == 0 and json.loads(out)["status"] == "recovered"
    expected = render_chapter_narration(moved, moved.chapters[0], "warn")
    assert (tmp_path / "chapters" / "001.txt").read_text() == expected
    assert len(list((tmp_path / "chapter-backups").iterdir())) == 1
