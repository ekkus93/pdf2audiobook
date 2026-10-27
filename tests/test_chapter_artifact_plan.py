"""Chapter artifact planning must preserve edits and reject ambiguous changes."""

import json

import pytest

from pdf2audiobook.chapter_artifacts import STATE_NAME, plan_chapter_artifacts
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock


def _manifest() -> BookManifest:
    return BookManifest(
        schema_version=3,
        input_sha256="source",
        title="Book",
        source_path="source",
        blocks=[DocumentBlock(id="b", page_index=0, text="Original.")],
        chapters=[Chapter(id="c", number=1, title="One", start_block=0, end_block=1, confidence=1)],
    )


def _publish_plan(folder, plan):
    chapter_dir = folder / "chapters"
    chapter_dir.mkdir(exist_ok=True)
    for name, content in plan.writes.items():
        (chapter_dir / name).write_bytes(content)
    (folder / STATE_NAME).write_text(json.dumps(plan.state), encoding="utf-8")


def test_edited_text_is_preserved_and_changed_source_conflicts(tmp_path):
    manifest = _manifest()
    _publish_plan(tmp_path, plan_chapter_artifacts(manifest, tmp_path, "warn"))
    chapter = tmp_path / "chapters" / "001.txt"
    chapter.write_text("Edited.\n", encoding="utf-8")
    plan = plan_chapter_artifacts(manifest, tmp_path, "warn")
    assert not plan.writes
    assert plan.state["chapters"]["c"]["edited"] is True
    manifest.blocks[0].text = "Changed source."
    with pytest.raises(ExtractionError, match="Chapter 1 text conflicts"):
        plan_chapter_artifacts(manifest, tmp_path, "warn")
    assert chapter.read_text(encoding="utf-8") == "Edited.\n"


def test_legacy_different_file_is_never_adopted(tmp_path):
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    chapter = chapter_dir / "001.txt"
    chapter.write_text("Private edit", encoding="utf-8")
    with pytest.raises(ExtractionError, match="Chapter 1 text conflicts") as exc:
        plan_chapter_artifacts(_manifest(), tmp_path, "warn")
    assert "Private edit" not in str(exc.value)
    assert chapter.read_text(encoding="utf-8") == "Private edit"


def test_missing_observed_edited_file_is_a_conflict(tmp_path):
    manifest = _manifest()
    _publish_plan(tmp_path, plan_chapter_artifacts(manifest, tmp_path, "warn"))
    chapter = tmp_path / "chapters" / "001.txt"
    chapter.write_text("Edited", encoding="utf-8")
    _publish_plan(tmp_path, plan_chapter_artifacts(manifest, tmp_path, "warn"))
    chapter.unlink()
    with pytest.raises(ExtractionError, match="Chapter 1 text conflicts"):
        plan_chapter_artifacts(manifest, tmp_path, "warn")


def test_unchanged_text_can_be_regenerated_after_source_change(tmp_path):
    manifest = _manifest()
    _publish_plan(tmp_path, plan_chapter_artifacts(manifest, tmp_path, "warn"))
    manifest.blocks[0].text = "New source."
    plan = plan_chapter_artifacts(manifest, tmp_path, "warn")
    assert b"New source." in plan.writes["001.txt"]


def test_invalid_metadata_fails_closed(tmp_path):
    (tmp_path / STATE_NAME).write_text('{"version": 1}', encoding="utf-8")
    with pytest.raises(ExtractionError, match="metadata is invalid"):
        plan_chapter_artifacts(_manifest(), tmp_path, "warn")


def test_missing_observed_edit_cannot_be_discarded_by_replacing_chapter_id(tmp_path):
    manifest = _manifest()
    _publish_plan(tmp_path, plan_chapter_artifacts(manifest, tmp_path, "warn"))
    chapter = tmp_path / "chapters" / "001.txt"
    chapter.write_text("Edited", encoding="utf-8")
    _publish_plan(tmp_path, plan_chapter_artifacts(manifest, tmp_path, "warn"))
    chapter.unlink()
    manifest.chapters[0].id = "replacement"
    with pytest.raises(ExtractionError, match="Chapter 1 text conflicts"):
        plan_chapter_artifacts(manifest, tmp_path, "warn")


def test_removed_edited_chapter_conflicts_before_deletion(tmp_path):
    from pdf2audiobook.document.structure import render_chapter_texts

    manifest = _manifest()
    manifest.blocks.append(DocumentBlock(id="b2", page_index=1, text="Second."))
    manifest.chapters.append(
        Chapter(id="c2", number=2, title="Two", start_block=1, end_block=2, confidence=1)
    )
    render_chapter_texts(manifest, tmp_path)
    target = tmp_path / "chapters" / "002.txt"
    target.write_text("Private second edit.", encoding="utf-8")
    manifest.chapters.pop()
    manifest.chapters[0].end_block = 2
    with pytest.raises(ExtractionError, match="Chapter 2 text conflicts"):
        plan_chapter_artifacts(manifest, tmp_path, "warn")
    assert target.read_text() == "Private second edit."


def test_unknown_stale_numbered_file_is_preserved(tmp_path):
    from pdf2audiobook.document.structure import render_chapter_texts

    manifest = _manifest()
    render_chapter_texts(manifest, tmp_path)
    target = tmp_path / "chapters" / "002.txt"
    target.write_text("Untracked notes", encoding="utf-8")
    with pytest.raises(ExtractionError, match="Chapter 2 text conflicts"):
        plan_chapter_artifacts(manifest, tmp_path, "warn")
    assert target.read_text() == "Untracked notes"


def test_footnote_policy_change_rejects_edited_chapter(tmp_path):
    from pdf2audiobook.document.structure import render_chapter_texts

    manifest = _manifest()
    render_chapter_texts(manifest, tmp_path, "warn")
    chapter = tmp_path / "chapters" / "001.txt"
    chapter.write_text("Private edit.", encoding="utf-8")
    with pytest.raises(ExtractionError, match="Chapter 1 text conflicts"):
        plan_chapter_artifacts(manifest, tmp_path, "end")
    assert chapter.read_text() == "Private edit."


def test_cleanup_change_conflicts_with_edited_file(tmp_path):
    from pdf2audiobook.document.structure import render_chapter_texts
    from pdf2audiobook.models import CleanupEdit

    manifest = _manifest()
    render_chapter_texts(manifest, tmp_path)
    chapter = tmp_path / "chapters" / "001.txt"
    chapter.write_text("Private edit.", encoding="utf-8")
    manifest.edits.append(
        CleanupEdit(
            block_id="b",
            original="Original.",
            replacement="Corrected.",
            reason="reviewed",
            confidence=1,
            accepted=True,
        )
    )
    with pytest.raises(ExtractionError, match="Chapter 1 text conflicts"):
        plan_chapter_artifacts(manifest, tmp_path, "warn")
    assert chapter.read_text() == "Private edit."


def test_renumbering_edited_chapter_does_not_replace_its_file(tmp_path):
    from pdf2audiobook.document.structure import render_chapter_texts

    manifest = _manifest()
    manifest.blocks.append(DocumentBlock(id="b2", page_index=1, text="Second."))
    manifest.chapters.append(
        Chapter(id="c2", number=2, title="Two", start_block=1, end_block=2, confidence=1)
    )
    render_chapter_texts(manifest, tmp_path)
    target = tmp_path / "chapters" / "001.txt"
    target.write_text("Edited first chapter.", encoding="utf-8")
    manifest.chapters[0].id, manifest.chapters[1].id = "c2", "c"
    with pytest.raises(ExtractionError, match="Chapter 1 text conflicts"):
        plan_chapter_artifacts(manifest, tmp_path, "warn")
    assert target.read_text() == "Edited first chapter."


def test_changed_file_after_planning_cannot_be_published(tmp_path):
    from pdf2audiobook.document.structure import render_chapter_texts
    from pdf2audiobook.review_transaction import JOURNAL, commit_artifacts
    from pdf2audiobook.workspace import workspace_lock

    manifest = _manifest()
    render_chapter_texts(manifest, tmp_path)
    manifest.blocks[0].text = "Changed source."
    target = tmp_path / "chapters" / "001.txt"
    with workspace_lock(tmp_path):
        plan = plan_chapter_artifacts(manifest, tmp_path, "warn")
        target.write_text("User edit during planning.", encoding="utf-8")
        with pytest.raises(ExtractionError, match="changed during review"):
            commit_artifacts(tmp_path, plan)
    assert target.read_text() == "User edit during planning."
    assert not (tmp_path / JOURNAL).exists()
