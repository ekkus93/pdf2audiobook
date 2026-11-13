"""Review transaction journals: invalid records, blocked recovery and commit guards.

Test coverage spec T3. A journal is never repaired automatically: anything
malformed or unsafe is refused with a fixed, content-free message and leaves
every workspace file as it was.
"""

import base64
import hashlib
import json

import pytest

from pdf2audiobook import review_transaction
from pdf2audiobook.chapter_artifacts import STATE_NAME, ArtifactPlan
from pdf2audiobook.errors import ExtractionError, PendingRecoveryError
from pdf2audiobook.review_transaction import (
    JOURNAL,
    ReviewRecoveryRequired,
    commit_artifacts,
    commit_review,
    recover_review_transaction,
)

INVALID = "The pending workspace update record is invalid; restore the workspace from a backup"
COVERAGE = b'{"coverage": "new"}\n'
STATE = b'{"state": "new"}\n'


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _entry(target, data, old=None):
    return {
        "target": target,
        "old": old,
        "new": _sha(data) if data is not None else None,
        "data": base64.b64encode(data).decode("ascii") if data is not None else None,
    }


def _record(*extra):
    return {
        "version": 1,
        "entries": [_entry("coverage.json", COVERAGE), _entry(STATE_NAME, STATE), *extra],
    }


def _write_journal(folder, record):
    payload = record if isinstance(record, bytes) else json.dumps(record).encode()
    (folder / JOURNAL).write_bytes(payload)


def _snapshot(folder):
    return {
        str(path.relative_to(folder)): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def _assert_content_free(message, folder):
    assert str(folder) not in message
    assert JOURNAL not in message
    assert "Errno" not in message


def test_a_valid_journal_is_completed_and_removed(tmp_path):
    """Control case: the journal format these tests corrupt is accepted."""
    _write_journal(tmp_path, _record())

    report = recover_review_transaction(tmp_path)

    assert report.status == "recovered"
    assert (tmp_path / "coverage.json").read_bytes() == COVERAGE
    assert (tmp_path / STATE_NAME).read_bytes() == STATE
    assert not (tmp_path / JOURNAL).exists()


def _with_entry(**changes):
    entry = _entry("chapters/001.txt", b"Chapter text.\n")
    entry.update(changes)
    return _record(entry)


def _without(target):
    record = _record()
    record["entries"] = [e for e in record["entries"] if e["target"] != target]
    return record


_INVALID_RECORDS = {
    "absolute-target": _with_entry(target="/etc/manifest.json"),
    "parent-target": _with_entry(target="../manifest.json"),
    "unknown-target": _with_entry(target="notes.txt"),
    "short-chapter-name": _with_entry(target="chapters/1.txt"),
    "extra-record-key": {**_record(), "extra": True},
    "wrong-version": {**_record(), "version": 2},
    "entries-not-a-list": {"version": 1, "entries": {}},
    "row-not-an-object": _record(["coverage.json"]),
    "row-missing-a-key": _record({"target": "chapters/001.txt", "old": None, "new": None}),
    "duplicate-target": _record(_entry("coverage.json", COVERAGE)),
    "target-not-a-string": _with_entry(target=7),
    "hash-not-hex": _with_entry(old="not-a-sha256"),
    "data-not-a-string": _with_entry(data=12),
    "bad-base64": _with_entry(data="***not base64***"),
    # Valid base64 with junk mixed in: lenient decoding would drop the junk and
    # the hash would then match, so only strict decoding refuses it.
    "base64-with-junk": _with_entry(
        data="!" + base64.b64encode(b"Chapter text.\n").decode("ascii")
    ),
    "data-without-hash": _with_entry(new=None),
    "hash-without-data": _with_entry(data=None),
    "data-hash-mismatch": _with_entry(new=_sha(b"other")),
    "missing-coverage": _without("coverage.json"),
    "missing-chapter-metadata": _without(STATE_NAME),
    "not-an-object": [1, 2, 3],
    "not-json": b"{not json",
}


@pytest.mark.parametrize("record", list(_INVALID_RECORDS.values()), ids=list(_INVALID_RECORDS))
def test_invalid_journal_is_refused_without_touching_the_workspace(tmp_path, record):
    """T3.a: every malformed or unsafe record gets the same fixed message."""
    (tmp_path / "coverage.json").write_bytes(b'{"coverage": "old"}\n')
    _write_journal(tmp_path, record)
    before = _snapshot(tmp_path)

    with pytest.raises(PendingRecoveryError) as error:
        recover_review_transaction(tmp_path)

    assert str(error.value) == INVALID
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_journal_that_is_not_a_regular_file_is_invalid(tmp_path, kind):
    """T3.a: a directory or symlink in the journal's place is never followed."""
    if kind == "directory":
        (tmp_path / JOURNAL).mkdir()
    else:
        outside = tmp_path / "elsewhere.json"
        outside.write_text(json.dumps(_record()))
        (tmp_path / JOURNAL).symlink_to(outside)

    with pytest.raises(PendingRecoveryError) as error:
        recover_review_transaction(tmp_path)

    assert str(error.value) == INVALID
    assert not (tmp_path / "coverage.json").exists()


def test_journal_target_under_a_symlinked_chapters_directory_is_unsafe(tmp_path):
    """T3.a: writing through a symlinked chapters directory is refused."""
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "chapters").symlink_to(outside, target_is_directory=True)
    _write_journal(tmp_path, _with_entry())

    with pytest.raises(PendingRecoveryError) as error:
        recover_review_transaction(tmp_path)

    assert str(error.value) == INVALID
    assert list(outside.iterdir()) == []


def test_changed_target_blocks_recovery_and_names_only_its_label(tmp_path):
    """T3.b: a file edited after the journal was written stops recovery."""
    (tmp_path / "coverage.json").write_bytes(b'{"edited": "by hand"}\n')
    _write_journal(tmp_path, _record())
    before = _snapshot(tmp_path)

    with pytest.raises(PendingRecoveryError) as error:
        recover_review_transaction(tmp_path)

    assert error.value.labels == ("coverage report",)
    assert "Changed since that update: coverage report." in str(error.value)
    _assert_content_free(str(error.value), tmp_path)
    assert _snapshot(tmp_path) == before


def test_back_up_changed_keeps_the_edited_file_and_finishes(tmp_path):
    """T3.b: with back_up_changed the edited file is copied aside, then replaced."""
    edited = b'{"edited": "by hand"}\n'
    (tmp_path / "coverage.json").write_bytes(edited)
    _write_journal(tmp_path, _record())

    report = recover_review_transaction(tmp_path, back_up_changed=True)

    assert report.status == "recovered"
    assert report.backed_up == ("coverage report",)
    assert len(report.backup_files) == 1
    assert (tmp_path / report.backup_files[0]).read_bytes() == edited
    assert (tmp_path / "coverage.json").read_bytes() == COVERAGE
    assert not (tmp_path / JOURNAL).exists()


def test_target_that_changes_during_recovery_blocks_it(tmp_path, monkeypatch):
    """T3.b: a file that changes between validation and writing is not overwritten."""
    _write_journal(tmp_path, _record())
    real_read = review_transaction._read_digest
    reads = {"coverage.json": 0}

    def changing_read(path):
        if path.name == "coverage.json":
            reads["coverage.json"] += 1
            if reads["coverage.json"] == 2:  # the second, per-write check
                return _sha(b"changed by another process")
        return real_read(path)

    monkeypatch.setattr(review_transaction, "_read_digest", changing_read)

    with pytest.raises(PendingRecoveryError) as error:
        recover_review_transaction(tmp_path)

    assert error.value.labels == ("coverage report",)
    assert not (tmp_path / "coverage.json").exists()
    assert (tmp_path / JOURNAL).exists()


def test_unexpected_failure_during_recovery_is_content_free(tmp_path, monkeypatch):
    """T3.b: an OS error while writing becomes the fixed retry message."""
    _write_journal(tmp_path, _record())

    def failing_write(path, data):
        raise OSError(13, "Permission denied", str(path))

    monkeypatch.setattr(review_transaction, "atomic_write", failing_write)

    with pytest.raises(PendingRecoveryError) as error:
        recover_review_transaction(tmp_path)

    assert str(error.value) == (
        "A previous workspace update could not be completed; this operation was not "
        "performed. Retry, or restore the workspace from a backup"
    )
    _assert_content_free(str(error.value), tmp_path)
    assert (tmp_path / JOURNAL).exists()


def _plan(**changes):
    values = {
        "writes": {},
        "deletes": (),
        "observed": {},
        "metadata_observed": {},
        "state": {"state": "new"},
        "coverage": {"coverage": "new"},
    }
    values.update(changes)
    return ArtifactPlan(**values)


def test_review_needs_a_manifest_json_workspace(tmp_path):
    """T3.c: a manifest under any other name is refused before anything is written."""
    with pytest.raises(ExtractionError, match="^Review requires a manifest.json workspace$"):
        commit_review(tmp_path / "book.json", None, _plan(), expected_manifest="0" * 64)

    assert list(tmp_path.iterdir()) == []


def test_chapter_metadata_changed_during_planning_is_refused(tmp_path):
    """T3.c: metadata that no longer matches what planning saw stops the commit."""
    (tmp_path / STATE_NAME).write_bytes(b'{"state": "edited meanwhile"}\n')
    plan = _plan(metadata_observed={STATE_NAME: _sha(b'{"state": "planned"}\n')})

    with pytest.raises(ExtractionError, match="^Chapter metadata changed during planning; retry$"):
        commit_artifacts(tmp_path, plan)

    assert not (tmp_path / JOURNAL).exists()
    assert not (tmp_path / "coverage.json").exists()


def test_transaction_over_the_size_limit_writes_no_journal(tmp_path, monkeypatch):
    """T3.c: an oversized journal is refused before it is written."""
    real_json_bytes = review_transaction._json_bytes

    class _Oversized(bytes):
        def __len__(self):
            return 512 * 1024 * 1024 + 1

    def json_bytes(value):
        encoded = real_json_bytes(value)
        return _Oversized(encoded) if isinstance(value, dict) and "entries" in value else encoded

    monkeypatch.setattr(review_transaction, "_json_bytes", json_bytes)

    with pytest.raises(
        ExtractionError, match="^Chapter transaction exceeds the workspace size limit$"
    ):
        commit_artifacts(tmp_path, _plan())

    assert list(tmp_path.iterdir()) == []


def test_commit_whose_recovery_is_blocked_reports_the_changed_labels(tmp_path, monkeypatch):
    """T3.c: a committed journal that can't be applied names what changed."""

    def blocked(folder, record, *, back_up_changed=False):
        raise review_transaction._RecoveryBlocked(["chapter 1"])

    monkeypatch.setattr(review_transaction, "_recover", blocked)

    with pytest.raises(ReviewRecoveryRequired) as error:
        commit_artifacts(tmp_path, _plan())

    assert str(error.value) == (
        "Workspace update was committed but needs recovery "
        "(chapter 1 changed); run pdf2audiobook recover on the manifest"
    )
    assert (tmp_path / JOURNAL).exists()
