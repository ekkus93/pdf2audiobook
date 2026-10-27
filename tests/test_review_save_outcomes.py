"""Review saves report truthful, distinct outcomes (R2, R3)."""

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from pdf2audiobook import review_transaction
from pdf2audiobook.document.structure import render_chapter_texts
from pdf2audiobook.errors import PendingRecoveryError
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock
from pdf2audiobook.review_transaction import JOURNAL, ReviewRecoveryRequired
from pdf2audiobook.review_ui import create_review_server, save_chapter_updates
from pdf2audiobook.workspace import write_manifest

PRIVATE = "PrivateHandEdit"


def _workspace(tmp_path: Path) -> tuple[Path, BookManifest]:
    manifest = BookManifest(
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
    path = tmp_path / "manifest.json"
    write_manifest(path, manifest)
    render_chapter_texts(manifest, tmp_path)
    return path, manifest


def _updates(manifest: BookManifest, *, end: int = 1) -> list[dict[str, object]]:
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


def _fail_manifest_publication(
    path: Path, manifest: BookManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = review_transaction.atomic_write

    def fail(target: Path, data: bytes) -> None:
        if target == path:
            raise OSError(PRIVATE)
        original(target, data)

    with monkeypatch.context() as patch:
        patch.setattr(review_transaction, "atomic_write", fail)
        with pytest.raises(ReviewRecoveryRequired):
            save_chapter_updates(path, _updates(manifest, end=2))
    assert (path.parent / JOURNAL).exists()


def _block_recovery(path: Path, monkeypatch: pytest.MonkeyPatch, manifest: BookManifest) -> None:
    """Leave a committed transaction that recovery must refuse to finish."""
    _fail_manifest_publication(path, manifest, monkeypatch)
    (path.parent / "chapters" / "001.txt").write_text(PRIVATE, encoding="utf-8")


@contextmanager
def _server(path: Path) -> Iterator[tuple[str, str]]:
    server = create_review_server(path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", server.review_token  # type: ignore[attr-defined]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def _post(url: str, token: str, updates: list[dict[str, object]]) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        url + "/api/chapters",
        data=json.dumps({"chapters": updates}).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": url,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_blocked_earlier_transaction_is_reported_as_not_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, manifest = _workspace(tmp_path)
    _block_recovery(path, monkeypatch, manifest)
    before = path.read_bytes()
    with pytest.raises(PendingRecoveryError) as raised:
        save_chapter_updates(path, _updates(manifest))
    assert PRIVATE not in str(raised.value) and str(tmp_path) not in str(raised.value)
    assert path.read_bytes() == before


def test_http_reports_blocked_earlier_transaction_as_not_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, manifest = _workspace(tmp_path)
    _block_recovery(path, monkeypatch, manifest)
    before = path.read_bytes()
    with _server(path) as (url, token):
        status, body = _post(url, token, _updates(manifest))
    assert status == 503
    assert body["outcome"] == "not_saved_pending_recovery"
    assert "not saved" in body["error"].lower()
    assert "committed" not in body["error"].lower()
    assert PRIVATE not in json.dumps(body) and str(tmp_path) not in json.dumps(body)
    assert path.read_bytes() == before


def test_http_reports_own_post_commit_failure_as_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, manifest = _workspace(tmp_path)
    original = review_transaction.atomic_write

    def fail(target: Path, data: bytes) -> None:
        if target == path:
            raise OSError(PRIVATE)
        original(target, data)

    with _server(path) as (url, token), monkeypatch.context() as patch:
        patch.setattr(review_transaction, "atomic_write", fail)
        status, body = _post(url, token, _updates(manifest, end=2))
    assert status == 503
    assert body["outcome"] == "committed_needs_recovery"
    assert "committed" in body["error"]
    assert PRIVATE not in json.dumps(body) and str(tmp_path) not in json.dumps(body)


def test_http_reports_chapter_conflict_with_number_and_changes_nothing(tmp_path: Path) -> None:
    path, manifest = _workspace(tmp_path)
    target = tmp_path / "chapters" / "001.txt"
    target.write_text(PRIVATE, encoding="utf-8")
    before = {item.name: item.read_bytes() for item in tmp_path.rglob("*") if item.is_file()}
    with _server(path) as (url, token):
        status, body = _post(url, token, _updates(manifest, end=2))
    assert status == 422
    assert body["outcome"] == "not_saved_conflict"
    assert body["chapter"] == 1
    assert "Chapter 1" in body["error"]
    assert PRIVATE not in json.dumps(body) and str(tmp_path) not in json.dumps(body)
    after = {item.name: item.read_bytes() for item in tmp_path.rglob("*") if item.is_file()}
    assert after == before
    assert not (tmp_path / JOURNAL).exists()


def test_other_validation_failures_keep_the_generic_message(tmp_path: Path) -> None:
    path, manifest = _workspace(tmp_path)
    with _server(path) as (url, token):
        status, body = _post(url, token, [])
    assert status == 400
    assert body == {"error": "Review update was invalid; no changes were saved"}


def test_conflict_error_carries_only_the_chapter_number(tmp_path: Path) -> None:
    from pdf2audiobook.errors import ChapterConflictError

    path, manifest = _workspace(tmp_path)
    (tmp_path / "chapters" / "001.txt").write_text(PRIVATE, encoding="utf-8")
    with pytest.raises(ChapterConflictError) as raised:
        save_chapter_updates(path, _updates(manifest, end=2))
    assert raised.value.chapter == 1
    assert PRIVATE not in str(raised.value)
