"""Read-only manifest access must not lock, create files, or run recovery (R1)."""

import fcntl
import json
import threading
import urllib.request
from pathlib import Path

import pytest

from pdf2audiobook import review_transaction
from pdf2audiobook.document.structure import render_chapter_texts
from pdf2audiobook.errors import PendingRecoveryError
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock
from pdf2audiobook.review_transaction import JOURNAL, ReviewRecoveryRequired
from pdf2audiobook.review_ui import create_review_server, save_chapter_updates
from pdf2audiobook.workspace import read_manifest, workspace_lock, write_manifest

PRIVATE = "private-workspace-name"


def _manifest() -> BookManifest:
    return BookManifest(
        schema_version=3,
        input_sha256="x",
        title="Book",
        source_path="source",
        blocks=[DocumentBlock(id="b", page_index=0, text="Body")],
        chapters=[
            Chapter(id="c", number=1, title="Before", start_block=0, end_block=1, confidence=1)
        ],
    )


def _workspace(tmp_path: Path) -> Path:
    path = tmp_path / "manifest.json"
    manifest = _manifest()
    write_manifest(path, manifest)
    render_chapter_texts(manifest, tmp_path)
    return path


def _snapshot(folder: Path) -> dict[str, bytes]:
    return {
        str(item.relative_to(folder)): item.read_bytes()
        for item in sorted(folder.rglob("*"))
        if item.is_file() and item.name != ".convert.lock"
    }


def _leave_pending_journal(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    updates = [
        {"id": "c", "title": "After", "start_block": 0, "end_block": 1},
    ]
    original = review_transaction.atomic_write

    def fail_manifest(target: Path, data: bytes) -> None:
        if target == path:
            raise OSError(PRIVATE)
        original(target, data)

    with monkeypatch.context() as patch:
        patch.setattr(review_transaction, "atomic_write", fail_manifest)
        with pytest.raises(ReviewRecoveryRequired):
            save_chapter_updates(path, updates)
    assert (path.parent / JOURNAL).exists()


def test_read_manifest_succeeds_while_another_holder_has_the_lock(tmp_path: Path) -> None:
    path = _workspace(tmp_path)
    with (tmp_path / ".convert.lock").open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        assert read_manifest(path).title == "Book"


def test_review_manifest_endpoint_succeeds_while_workspace_is_locked(tmp_path: Path) -> None:
    path = _workspace(tmp_path)
    server = create_review_server(path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with (tmp_path / ".convert.lock").open("a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            request = urllib.request.Request(
                url + "/api/manifest", headers={"Authorization": f"Bearer {server.review_token}"}
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                assert response.status == 200
                assert json.loads(response.read())["title"] == "Book"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_read_manifest_on_missing_workspace_creates_nothing(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent" / "sub" / "manifest.json"
    with pytest.raises(Exception, match="Cannot read or validate audiobook manifest"):
        read_manifest(missing)
    assert not (tmp_path / "nonexistent").exists()


def test_read_manifest_does_not_create_a_lock_file(tmp_path: Path) -> None:
    path = _workspace(tmp_path)
    (tmp_path / ".convert.lock").unlink()
    read_manifest(path)
    assert not (tmp_path / ".convert.lock").exists()


def test_pending_journal_blocks_read_without_modifying_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _workspace(tmp_path)
    _leave_pending_journal(path, monkeypatch)
    before = _snapshot(tmp_path)
    with pytest.raises(PendingRecoveryError):
        read_manifest(path)
    assert _snapshot(tmp_path) == before


def test_writer_lock_recovers_pending_journal_before_a_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _workspace(tmp_path)
    _leave_pending_journal(path, monkeypatch)
    with workspace_lock(tmp_path):
        assert read_manifest(path).chapters[0].title == "After"
    assert not (tmp_path / JOURNAL).exists()


def test_review_manifest_endpoint_reports_pending_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import urllib.error

    path = _workspace(tmp_path)
    _leave_pending_journal(path, monkeypatch)
    server = create_review_server(path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        request = urllib.request.Request(
            url + "/api/manifest", headers={"Authorization": f"Bearer {server.review_token}"}
        )
        with pytest.raises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(request, timeout=3)
        assert raised.value.code == 503
        assert "pending" in json.loads(raised.value.read())["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
