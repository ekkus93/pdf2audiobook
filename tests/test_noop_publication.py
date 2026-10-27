"""Publishing an unchanged artifact set writes nothing (R7)."""

from pathlib import Path

import pytest

from pdf2audiobook import review_transaction
from pdf2audiobook.chapter_artifacts import plan_chapter_artifacts
from pdf2audiobook.document.structure import render_chapter_texts
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock
from pdf2audiobook.review_transaction import JOURNAL, commit_artifacts
from pdf2audiobook.workspace import write_manifest


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


def _stamps(folder: Path) -> dict[str, int]:
    return {
        str(item.relative_to(folder)): item.stat().st_mtime_ns
        for item in sorted(folder.rglob("*"))
        if item.is_file() and item.name != ".convert.lock"
    }


def test_rendering_an_up_to_date_workspace_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    write_manifest(tmp_path / "manifest.json", manifest)
    render_chapter_texts(manifest, tmp_path)
    before = _stamps(tmp_path)
    calls: list[Path] = []
    original = review_transaction.atomic_write

    def spy(target: Path, data: bytes) -> None:
        calls.append(target)
        original(target, data)

    with monkeypatch.context() as patch:
        patch.setattr(review_transaction, "atomic_write", spy)
        render_chapter_texts(manifest, tmp_path)
    assert calls == []
    assert _stamps(tmp_path) == before
    assert not (tmp_path / JOURNAL).exists()


def test_unchanged_review_manifest_publication_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    path = tmp_path / "manifest.json"
    write_manifest(path, manifest)
    render_chapter_texts(manifest, tmp_path)
    before = _stamps(tmp_path)
    plan = plan_chapter_artifacts(manifest, tmp_path, "warn")
    from pdf2audiobook.chapter_artifacts import _read_digest

    calls: list[Path] = []
    original = review_transaction.atomic_write

    def spy(target: Path, data: bytes) -> None:
        calls.append(target)
        original(target, data)

    with monkeypatch.context() as patch:
        patch.setattr(review_transaction, "atomic_write", spy)
        review_transaction.commit_review(
            path, manifest, plan, expected_manifest=_read_digest(path) or ""
        )
    assert calls == []
    assert _stamps(tmp_path) == before


def test_a_noop_plan_still_detects_a_concurrent_change(tmp_path: Path) -> None:
    manifest = _manifest()
    write_manifest(tmp_path / "manifest.json", manifest)
    render_chapter_texts(manifest, tmp_path)
    plan = plan_chapter_artifacts(manifest, tmp_path, "warn")
    target = tmp_path / "chapters" / "001.txt"
    target.write_text("Changed after planning.", encoding="utf-8")
    with pytest.raises(ExtractionError, match="changed during review"):
        commit_artifacts(tmp_path, plan)
    assert target.read_text() == "Changed after planning."
    assert not (tmp_path / JOURNAL).exists()


def test_a_changed_chapter_is_still_published(tmp_path: Path) -> None:
    manifest = _manifest()
    write_manifest(tmp_path / "manifest.json", manifest)
    render_chapter_texts(manifest, tmp_path)
    (tmp_path / "chapters" / "002.txt").unlink()
    render_chapter_texts(manifest, tmp_path)
    assert (tmp_path / "chapters" / "002.txt").exists()
