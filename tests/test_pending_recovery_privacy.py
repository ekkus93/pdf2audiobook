"""Pending-recovery errors must be content-free (R1)."""

from pathlib import Path

import pytest

from pdf2audiobook import review_transaction
from pdf2audiobook.document.structure import render_chapter_texts
from pdf2audiobook.errors import PendingRecoveryError
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock
from pdf2audiobook.review_transaction import ReviewRecoveryRequired
from pdf2audiobook.review_ui import save_chapter_updates
from pdf2audiobook.workspace import read_manifest, write_manifest

PRIVATE_TEXT = "SecretBookSentence"


def test_pending_recovery_error_does_not_echo_text_or_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "private-folder-name"
    folder.mkdir()
    manifest = BookManifest(
        schema_version=3,
        input_sha256="x",
        title="Book",
        source_path="source",
        blocks=[DocumentBlock(id="b", page_index=0, text=PRIVATE_TEXT)],
        chapters=[
            Chapter(id="c", number=1, title="Before", start_block=0, end_block=1, confidence=1)
        ],
    )
    path = folder / "manifest.json"
    write_manifest(path, manifest)
    render_chapter_texts(manifest, folder)
    original = review_transaction.atomic_write

    def fail_manifest(target: Path, data: bytes) -> None:
        if target == path:
            raise OSError(PRIVATE_TEXT)
        original(target, data)

    with monkeypatch.context() as patch:
        patch.setattr(review_transaction, "atomic_write", fail_manifest)
        with pytest.raises(ReviewRecoveryRequired):
            save_chapter_updates(
                path, [{"id": "c", "title": "After", "start_block": 0, "end_block": 1}]
            )
    with pytest.raises(PendingRecoveryError) as raised:
        read_manifest(path)
    message = str(raised.value)
    assert PRIVATE_TEXT not in message
    assert "private-folder-name" not in message
    assert str(tmp_path) not in message
