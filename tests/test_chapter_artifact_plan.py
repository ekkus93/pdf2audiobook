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


# --- Hand-edit protection (test coverage round 2, U2) --------------------------

_INSPECT = "Cannot inspect chapter text; check workspace files"
_INVALID_METADATA = "Chapter artifact metadata is invalid; restore it from a backup"


def _two_chapters() -> BookManifest:
    manifest = _manifest()
    manifest.blocks.append(DocumentBlock(id="b2", page_index=1, text="Second."))
    manifest.chapters.append(
        Chapter(id="c2", number=2, title="Two", start_block=1, end_block=2, confidence=1)
    )
    return manifest


def _files(folder):
    return {
        str(path.relative_to(folder)): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


@pytest.mark.parametrize("kind", ["symlink", "directory"])
def test_chapter_path_that_is_not_a_regular_file_is_refused(tmp_path, kind):
    """U2.a: a symlink or directory in a chapter's place is never read or written."""
    from pdf2audiobook.document.structure import render_chapter_texts

    manifest = _manifest()
    render_chapter_texts(manifest, tmp_path)
    chapter = tmp_path / "chapters" / "001.txt"
    chapter.unlink()
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("Private text elsewhere.", encoding="utf-8")
    if kind == "symlink":
        chapter.symlink_to(outside)
    else:
        chapter.mkdir()

    with pytest.raises(ExtractionError) as error:
        plan_chapter_artifacts(manifest, tmp_path, "warn")

    assert str(error.value) == _INSPECT
    assert str(tmp_path) not in str(error.value)
    assert outside.read_text(encoding="utf-8") == "Private text elsewhere."


def test_named_pipe_in_a_chapter_place_is_refused_without_blocking(tmp_path):
    """U2.a: a FIFO is not a regular file; opening it to read would block forever."""
    import os
    import threading

    from pdf2audiobook.document.structure import render_chapter_texts

    manifest = _manifest()
    render_chapter_texts(manifest, tmp_path)
    chapter = tmp_path / "chapters" / "001.txt"
    chapter.unlink()
    os.mkfifo(chapter)
    outcome = {}

    def plan():
        try:
            plan_chapter_artifacts(manifest, tmp_path, "warn")
        except ExtractionError as error:
            outcome["message"] = str(error)

    worker = threading.Thread(target=plan, daemon=True)
    worker.start()
    worker.join(timeout=5)
    if worker.is_alive():
        # Release the blocked reader before failing: open and close a writer end.
        os.close(os.open(chapter, os.O_RDWR | os.O_NONBLOCK))
        worker.join(timeout=5)
        pytest.fail("planning blocked on a named pipe")

    assert outcome == {"message": _INSPECT}


def _state(**changes):
    record = {"number": 1, "generated": "a" * 64, "identity": "b" * 64, "edited": False}
    state = {"version": 1, "footnotes": "warn", "chapters": {"c": record}}
    for key, value in changes.items():
        if key.startswith("record_"):
            field = key.removeprefix("record_")
            if value is _DROP:
                del record[field]
            else:
                record[field] = value
        elif value is _DROP:
            del state[key]
        else:
            state[key] = value
    return state


_DROP = object()


@pytest.mark.parametrize(
    "state",
    [
        ["not", "an", "object"],
        _state(extra=True),
        _state(version=_DROP),
        _state(version=2),
        _state(footnotes=7),
        _state(footnotes="aside"),
        _state(chapters=[]),
        _state(chapters={"c": "not a record"}),
        # A list of exactly the key names passes the key-set check; only the
        # type check stops it before record.get().
        _state(chapters={"c": ["number", "generated", "identity", "edited"]}),
        _state(record_extra=1),
        _state(record_number=_DROP),
        _state(record_number=True),
        _state(record_number="1"),
        _state(record_number=0),
        _state(chapters={"c": _state()["chapters"]["c"], "d": _state()["chapters"]["c"]}),
        _state(record_generated=7),
        _state(record_generated="A" * 64),
        _state(record_identity=None),
        _state(record_identity="b" * 63),
        _state(record_edited="no"),
    ],
    ids=[
        "not-an-object",
        "extra-key",
        "missing-version",
        "wrong-version",
        "policy-not-a-string",
        "unknown-policy",
        "chapters-not-a-mapping",
        "record-not-an-object",
        "record-is-a-list-of-the-keys",
        "record-extra-key",
        "record-missing-number",
        "number-bool",
        "number-string",
        "number-zero",
        "duplicate-number",
        "generated-not-a-string",
        "generated-not-a-digest",
        "identity-not-a-string",
        "identity-short",
        "edited-not-a-bool",
    ],
)
def test_invalid_chapter_metadata_is_refused_with_files_unchanged(tmp_path, state):
    """U2.b: any malformed metadata is refused before planning, never repaired."""
    (tmp_path / STATE_NAME).write_text(json.dumps(state), encoding="utf-8")
    before = _files(tmp_path)

    with pytest.raises(ExtractionError) as error:
        plan_chapter_artifacts(_manifest(), tmp_path, "warn")

    assert str(error.value) == _INVALID_METADATA
    assert _files(tmp_path) == before


def test_valid_metadata_control_case_is_accepted(tmp_path):
    """U2.b control: the record shape the cases above corrupt is accepted."""
    from pdf2audiobook.chapter_artifacts import load_artifact_state

    (tmp_path / STATE_NAME).write_text(json.dumps(_state()), encoding="utf-8")

    assert load_artifact_state(tmp_path) == _state()


def test_unknown_footnote_policy_is_refused(tmp_path):
    """U2.c: planning refuses a policy it doesn't know before reading anything."""
    with pytest.raises(ExtractionError, match="^Chapter footnote policy is invalid$"):
        plan_chapter_artifacts(_manifest(), tmp_path, "aside")

    assert list(tmp_path.iterdir()) == []


def test_metadata_changed_while_planning_is_refused(tmp_path, monkeypatch):
    """U2.c: metadata rewritten between its two reads stops planning."""
    from pdf2audiobook import chapter_artifacts
    from pdf2audiobook.document.structure import render_chapter_texts

    manifest = _manifest()
    render_chapter_texts(manifest, tmp_path)
    real_load = chapter_artifacts.load_artifact_state

    def load_then_rewrite(folder):
        state = real_load(folder)
        (folder / STATE_NAME).write_text(json.dumps(state) + "\n", encoding="utf-8")
        return state

    monkeypatch.setattr(chapter_artifacts, "load_artifact_state", load_then_rewrite)

    with pytest.raises(
        ExtractionError, match="^Chapter artifact metadata changed during planning; retry$"
    ):
        plan_chapter_artifacts(manifest, tmp_path, "warn")


def test_duplicate_chapter_ids_are_refused(tmp_path):
    """U2.c: two chapters with one ID can't both own a file."""
    manifest = _two_chapters()
    manifest.chapters[1].id = "c"

    with pytest.raises(ExtractionError, match="^Duplicate chapter IDs in manifest$"):
        plan_chapter_artifacts(manifest, tmp_path, "warn")

    assert list(tmp_path.iterdir()) == []


def _edited_and_recorded(folder, manifest, number, text):
    """Edit a chapter file and record the edit in metadata, as a later run would."""
    (folder / "chapters" / f"{number:03d}.txt").write_text(text, encoding="utf-8")
    _publish_plan(folder, plan_chapter_artifacts(manifest, folder, "warn"))


def test_new_chapter_number_with_a_different_file_conflicts(tmp_path):
    """U2.d: a new chapter never overwrites an untracked file at its number."""
    from pdf2audiobook.chapter_artifacts import find_chapter_conflicts
    from pdf2audiobook.document.structure import render_chapter_texts

    render_chapter_texts(_manifest(), tmp_path)
    target = tmp_path / "chapters" / "002.txt"
    target.write_text("Private notes.", encoding="utf-8")
    manifest = _two_chapters()

    with pytest.raises(ExtractionError, match="^Chapter 2 text conflicts"):
        plan_chapter_artifacts(manifest, tmp_path, "warn")
    assert find_chapter_conflicts(manifest, tmp_path, "warn") == [2]
    assert target.read_text(encoding="utf-8") == "Private notes."


def test_deleted_hand_edited_chapter_conflicts(tmp_path):
    """U2.d: a hand-edited chapter whose file was deleted is not silently regenerated."""
    from pdf2audiobook.chapter_artifacts import find_chapter_conflicts
    from pdf2audiobook.document.structure import render_chapter_texts

    manifest = _manifest()
    render_chapter_texts(manifest, tmp_path)
    _edited_and_recorded(tmp_path, manifest, 1, "Edited.\n")
    assert json.loads((tmp_path / STATE_NAME).read_text())["chapters"]["c"]["edited"] is True
    (tmp_path / "chapters" / "001.txt").unlink()

    with pytest.raises(ExtractionError, match="^Chapter 1 text conflicts"):
        plan_chapter_artifacts(manifest, tmp_path, "warn")
    assert find_chapter_conflicts(manifest, tmp_path, "warn") == [1]
    assert not (tmp_path / "chapters" / "001.txt").exists()


def test_all_conflicts_are_collected_once_each_and_files_survive(tmp_path):
    """U2.d: collect mode reports every conflicting number once, in order."""
    from pdf2audiobook.chapter_artifacts import find_chapter_conflicts
    from pdf2audiobook.document.structure import render_chapter_texts

    manifest = _two_chapters()
    manifest.blocks.append(DocumentBlock(id="b3", page_index=2, text="Third."))
    manifest.chapters.append(
        Chapter(id="c3", number=3, title="Three", start_block=2, end_block=3, confidence=1)
    )
    render_chapter_texts(manifest, tmp_path)
    _edited_and_recorded(tmp_path, manifest, 1, "Edited one.\n")
    chapters = tmp_path / "chapters"
    (chapters / "001.txt").unlink()  # 1: deleted after its edit was recorded
    (chapters / "002.txt").write_text("Edited two.\n", encoding="utf-8")  # 2: range changes
    (chapters / "003.txt").write_text("Edited three.\n", encoding="utf-8")  # 3: removed
    (chapters / "005.txt").write_text("Untracked notes.\n", encoding="utf-8")  # 5: unknown
    manifest.chapters.pop()
    manifest.chapters[1].end_block = 3
    before = _files(tmp_path)

    assert find_chapter_conflicts(manifest, tmp_path, "warn") == [1, 2, 3, 5]
    # Raise mode stops at the first: chapters no longer in the manifest are checked first.
    with pytest.raises(ExtractionError, match="^Chapter 3 text conflicts"):
        plan_chapter_artifacts(manifest, tmp_path, "warn")
    assert _files(tmp_path) == before


def _swap_ids(manifest):
    manifest.chapters[0].id, manifest.chapters[1].id = "c2", "c"


def test_chapter_moved_onto_an_edited_occupant_conflicts(tmp_path):
    """U2.d: a chapter moved onto a slot whose old owner was edited conflicts."""
    from pdf2audiobook.chapter_artifacts import find_chapter_conflicts
    from pdf2audiobook.document.structure import render_chapter_texts

    manifest = _two_chapters()
    render_chapter_texts(manifest, tmp_path)
    target = tmp_path / "chapters" / "002.txt"
    target.write_text("Edited two.\n", encoding="utf-8")
    _swap_ids(manifest)  # c now numbers 2, onto c2's edited file

    assert find_chapter_conflicts(manifest, tmp_path, "warn") == [2]
    with pytest.raises(ExtractionError, match="^Chapter 2 text conflicts"):
        plan_chapter_artifacts(manifest, tmp_path, "warn")
    assert target.read_text(encoding="utf-8") == "Edited two.\n"


def test_forced_number_skips_the_edit_check_and_is_regenerated(tmp_path):
    """U2.d: a number named in force (already backed up) is replaced, not a conflict."""
    from pdf2audiobook.document.structure import render_chapter_texts

    manifest = _two_chapters()
    render_chapter_texts(manifest, tmp_path)
    (tmp_path / "chapters" / "002.txt").write_text("Edited two.\n", encoding="utf-8")
    _swap_ids(manifest)

    plan = plan_chapter_artifacts(manifest, tmp_path, "warn", force=frozenset({2}))

    # IDs swap but block ranges stay, so only slot 2's edited file is replaced.
    assert set(plan.writes) == {"002.txt"}
    assert plan.writes["002.txt"].decode("utf-8").startswith("Second.")
    assert plan.state["chapters"]["c"]["edited"] is False
    assert plan.deletes == ()


def test_anchor_edits_rule_out_the_warn_policy(tmp_path):
    """U2.d (line 127): footnote anchor edits mean the legacy policy isn't warn."""
    from pdf2audiobook.chapter_artifacts import resolve_footnote_policy
    from pdf2audiobook.errors import FootnotePolicyUnknownError
    from pdf2audiobook.models import CleanupEdit

    manifest = _manifest()
    manifest.edits.append(
        CleanupEdit(
            block_id="b",
            original="1",
            replacement="",
            reason="footnote anchor marker 1 (note handled)",
            confidence=1,
            accepted=True,
            provider="deterministic",
        )
    )

    # No chapter files: without anchor edits this would resolve to warn.
    with pytest.raises(FootnotePolicyUnknownError):
        resolve_footnote_policy(manifest, tmp_path)
    manifest.edits.clear()
    assert resolve_footnote_policy(manifest, tmp_path) == "warn"
