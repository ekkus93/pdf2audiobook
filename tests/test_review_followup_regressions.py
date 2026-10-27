"""Regression coverage for editable narration and review persistence."""

from pathlib import Path

import fitz
import numpy as np
import pytest
from typer.testing import CliRunner

from pdf2audiobook.config import Settings
from pdf2audiobook.document.structure import render_chapter_texts
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock
from pdf2audiobook.pipeline import analyze_book, convert_book
from pdf2audiobook.review_transaction import JOURNAL, ReviewRecoveryRequired
from pdf2audiobook.review_ui import save_chapter_updates
from pdf2audiobook.workspace import read_manifest, write_manifest


def _updates(manifest: BookManifest) -> list[dict[str, object]]:
    return [
        {
            "id": chapter.id,
            "title": chapter.title,
            "start_block": chapter.start_block,
            "end_block": chapter.end_block,
        }
        for chapter in manifest.chapters
    ]


def test_analyze_resume_preserves_edited_narration_and_voice_marker(tmp_path: Path) -> None:
    source = tmp_path / "book.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Chapter 1")
    page.insert_text((72, 120), "Original narration.")
    doc.save(source)
    doc.close()
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.llm.enabled = False
    settings.pdf.ocr = "never"
    manifest_path = analyze_book(source, settings)
    manifest = read_manifest(manifest_path)
    manifest.chapters[0].manually_approved = True
    write_manifest(manifest_path, manifest)
    chapter_path = manifest_path.parent / "chapters" / "001.txt"
    edited = "Corrected narration.\n\n[[voice:Bella]]\n\nDialogue.\n"
    chapter_path.write_text(edited, encoding="utf-8")
    analyze_book(source, settings)
    assert chapter_path.read_text(encoding="utf-8") == edited


def test_failed_review_save_does_not_claim_uncommitted_state(tmp_path: Path, monkeypatch) -> None:
    manifest = BookManifest(
        schema_version=3,
        input_sha256="x",
        title="Book",
        source_path="source",
        blocks=[DocumentBlock(id="b", page_index=0, text="Body")],
        chapters=[
            Chapter(id="c", number=1, title="Before", start_block=0, end_block=1, confidence=1)
        ],
    )
    path = tmp_path / "manifest.json"
    write_manifest(path, manifest)
    updates = _updates(manifest)
    updates[0]["title"] = "After"

    def fail_staging(*_args, **_kwargs):
        raise OSError("simulated failure")

    monkeypatch.setattr("pdf2audiobook.review_transaction.atomic_write", fail_staging)
    with pytest.raises(OSError):
        save_chapter_updates(path, updates)
    assert read_manifest(path).chapters[0].title == "Before"


def test_review_preserves_recorded_end_footnote_policy(tmp_path: Path) -> None:
    manifest = BookManifest(
        schema_version=3,
        input_sha256="x",
        title="Book",
        source_path="source",
        blocks=[
            DocumentBlock(id="a", page_index=0, text="First paragraph."),
            DocumentBlock(id="n", page_index=0, text="1 Footnote.", kind="footnote"),
            DocumentBlock(id="b", page_index=0, text="Last paragraph."),
        ],
        chapters=[
            Chapter(id="c", number=1, title="Chapter", start_block=0, end_block=3, confidence=1)
        ],
    )
    path = tmp_path / "manifest.json"
    write_manifest(path, manifest)
    render_chapter_texts(manifest, tmp_path, "end")
    chapter_path = tmp_path / "chapters" / "001.txt"
    before = chapter_path.read_bytes()
    assert before.index(b"Last paragraph") < before.index(b"Footnote")
    save_chapter_updates(path, _updates(manifest))
    assert chapter_path.read_bytes() == before


def test_committed_review_recovers_after_interrupted_publication(
    tmp_path: Path, monkeypatch
) -> None:
    from pdf2audiobook import review_transaction

    manifest = BookManifest(
        schema_version=3,
        input_sha256="x",
        title="Book",
        source_path="source",
        blocks=[DocumentBlock(id="b", page_index=0, text="Body")],
        chapters=[
            Chapter(id="c", number=1, title="Before", start_block=0, end_block=1, confidence=1)
        ],
    )
    path = tmp_path / "manifest.json"
    write_manifest(path, manifest)
    render_chapter_texts(manifest, tmp_path)
    updates = _updates(manifest)
    updates[0]["title"] = "After"
    original = review_transaction.atomic_write

    def fail_manifest(target, data):
        if target == path:
            raise OSError("simulated failure")
        original(target, data)

    with monkeypatch.context() as patch:
        patch.setattr(review_transaction, "atomic_write", fail_manifest)
        with pytest.raises(ReviewRecoveryRequired, match="committed"):
            save_chapter_updates(path, updates)
        assert (tmp_path / JOURNAL).exists()
    assert read_manifest(path).chapters[0].title == "After"
    assert not (tmp_path / JOURNAL).exists()
    assert read_manifest(path).chapters[0].title == "After"


def test_edited_narration_reaches_synthesis_and_packaging(tmp_path: Path, monkeypatch) -> None:
    from pdf2audiobook.cli import app

    source = tmp_path / "book.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Chapter 1")
    page.insert_text((72, 120), "Original narration.")
    doc.save(source)
    doc.close()
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.llm.enabled = False
    settings.pdf.ocr = "never"
    path = analyze_book(source, settings)
    manifest = read_manifest(path)
    manifest.chapters[0].manually_approved = True
    write_manifest(path, manifest)
    chapter = path.parent / "chapters" / "001.txt"
    edited = "Corrected narration.\n\n[[voice:Bella]]\n\nSpoken dialogue.\n"
    chapter.write_text(edited, encoding="utf-8")
    calls = []

    class Provider:
        sample_rate = 24000
        max_chars_per_chunk = 350

        def list_voices(self):
            return ["Jasper", "Bella"]

        def generate(self, text, *, voice, speed):
            calls.append((text, voice))
            return np.ones(240, dtype=np.float32) * 0.1

    def encode(_samples, _rate, target, **_kwargs):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"synthetic audio")

    convert_book(source, settings, tts_provider=Provider(), encoder=encode)
    assert chapter.read_text(encoding="utf-8") == edited
    assert any("Corrected narration" in text and voice == "Jasper" for text, voice in calls)
    assert any("Spoken dialogue" in text and voice == "Bella" for text, voice in calls)
    monkeypatch.setattr("pdf2audiobook.audio.encode_m4b", lambda *_a, **_k: tmp_path / "book.m4b")
    args = ["pack-m4b", str(path), "--output", str(tmp_path / "book.m4b"), "--no-config"]
    assert CliRunner().invoke(app, args).exit_code == 0
    chapter.write_text(edited + "Further change.\n", encoding="utf-8")
    assert CliRunner().invoke(app, args).exit_code == 6


@pytest.mark.parametrize("policy", ["warn", "inline", "end", "omit"])
def test_review_save_preserves_all_footnote_policies(tmp_path: Path, policy: str) -> None:
    from pdf2audiobook.document.structure import footnote_omit_edits

    blocks = [
        DocumentBlock(id="a", page_index=0, text="A sentence.1", kind="paragraph"),
        DocumentBlock(id="b", page_index=0, text="Another paragraph.", kind="paragraph"),
        DocumentBlock(id="n", page_index=0, text="1 Footnote.", kind="footnote"),
        DocumentBlock(id="c", page_index=0, text="Last paragraph.", kind="paragraph"),
    ]
    manifest = BookManifest(
        schema_version=3,
        input_sha256="x",
        title="Book",
        source_path="source",
        blocks=blocks,
        edits=footnote_omit_edits(blocks) if policy == "omit" else [],
        chapters=[
            Chapter(id="c", number=1, title="Chapter", start_block=0, end_block=4, confidence=1)
        ],
    )
    path = tmp_path / "manifest.json"
    write_manifest(path, manifest)
    render_chapter_texts(manifest, tmp_path, policy)
    target = tmp_path / "chapters" / "001.txt"
    before = target.read_bytes()
    save_chapter_updates(path, _updates(manifest))
    assert target.read_bytes() == before
    if policy == "omit":
        assert b"Footnote" not in before
    elif policy == "end":
        assert before.index(b"Last paragraph") < before.index(b"Footnote")
    elif policy == "inline":
        assert before.index(b"Footnote") < before.index(b"Another paragraph")
    else:
        assert (
            before.index(b"Another paragraph")
            < before.index(b"Footnote")
            < before.index(b"Last paragraph")
        )


@pytest.mark.parametrize(
    "target_name",
    ["manifest.json", "coverage.json", "chapter-artifacts.json", "001.txt", "002.txt"],
)
def test_interrupted_review_recovers_each_artifact(tmp_path: Path, monkeypatch, target_name: str):
    from pdf2audiobook import review_transaction

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
    if target_name == "coverage.json":
        (tmp_path / "coverage.json").write_text("{}", encoding="utf-8")
    updates = _updates(manifest)
    updates[0]["end_block"] = 2
    updates[1]["start_block"] = 2
    original = review_transaction.atomic_write

    def fail_target(target, data):
        if target.name == target_name:
            raise OSError("private simulated failure")
        original(target, data)

    with monkeypatch.context() as patch:
        patch.setattr(review_transaction, "atomic_write", fail_target)
        with pytest.raises(ReviewRecoveryRequired, match="committed") as exc:
            save_chapter_updates(path, updates)
        assert "private" not in str(exc.value)
        assert (tmp_path / JOURNAL).exists()
    recovered = read_manifest(path)
    assert recovered.chapters[0].end_block == 2
    assert recovered.chapters[1].start_block == 2
    assert "Body 1" in (tmp_path / "chapters" / "001.txt").read_text()
    assert "Body 1" not in (tmp_path / "chapters" / "002.txt").read_text()
    assert not (tmp_path / JOURNAL).exists()


def test_recovery_refuses_to_overwrite_an_edit_after_commit(tmp_path: Path, monkeypatch):
    from pdf2audiobook import review_transaction

    blocks = [DocumentBlock(id=f"b{i}", page_index=0, text=f"Body {i}.") for i in range(3)]
    manifest = BookManifest(
        schema_version=3,
        input_sha256="x",
        title="Book",
        source_path="source",
        blocks=blocks,
        chapters=[
            Chapter(id="a", number=1, title="One", start_block=0, end_block=1, confidence=1),
            Chapter(id="b", number=2, title="Two", start_block=1, end_block=3, confidence=1),
        ],
    )
    path = tmp_path / "manifest.json"
    write_manifest(path, manifest)
    render_chapter_texts(manifest, tmp_path)
    target = tmp_path / "chapters" / "001.txt"
    original_text = target.read_bytes()
    updates = _updates(manifest)
    updates[0]["end_block"] = 2
    updates[1]["start_block"] = 2
    original_write = review_transaction.atomic_write

    def fail_chapter(file, data):
        if file == target:
            raise OSError("failure")
        original_write(file, data)

    with monkeypatch.context() as patch:
        patch.setattr(review_transaction, "atomic_write", fail_chapter)
        with pytest.raises(ReviewRecoveryRequired):
            save_chapter_updates(path, updates)
    target.write_text("User changed this during recovery.", encoding="utf-8")
    with pytest.raises(ReviewRecoveryRequired):
        read_manifest(path)
    assert target.read_text() == "User changed this during recovery."
    assert (tmp_path / JOURNAL).exists()
    target.write_bytes(original_text)
    assert read_manifest(path).chapters[0].end_block == 2
    assert not (tmp_path / JOURNAL).exists()


def test_review_http_reports_committed_recovery(tmp_path: Path, monkeypatch):
    import json
    import threading
    import urllib.error
    import urllib.request

    from pdf2audiobook import review_transaction
    from pdf2audiobook.review_ui import create_review_server

    manifest = BookManifest(
        schema_version=3,
        input_sha256="x",
        title="Book",
        source_path="source",
        blocks=[DocumentBlock(id="b", page_index=0, text="Body")],
        chapters=[
            Chapter(id="c", number=1, title="Before", start_block=0, end_block=1, confidence=1)
        ],
    )
    path = tmp_path / "manifest.json"
    write_manifest(path, manifest)
    render_chapter_texts(manifest, tmp_path)
    updates = _updates(manifest)
    updates[0]["title"] = "After"
    server = create_review_server(path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    original = review_transaction.atomic_write

    def fail_manifest(target, data):
        if target == path:
            raise OSError("private failure")
        original(target, data)

    try:
        request = urllib.request.Request(
            url + "/api/chapters",
            data=json.dumps({"chapters": updates}).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {server.review_token}",
                "Origin": url,
                "Content-Type": "application/json",
            },
        )
        with monkeypatch.context() as patch:
            patch.setattr(review_transaction, "atomic_write", fail_manifest)
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(request, timeout=3)
            assert exc.value.code == 503
            response = json.loads(exc.value.read())
            assert "committed" in response["error"]
            assert "private" not in response["error"]
        assert read_manifest(path).chapters[0].title == "After"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_empty_edited_chapter_is_skipped_after_approval(tmp_path: Path):
    from pdf2audiobook.pipeline import prepare_chapter_selection

    manifest = BookManifest(
        schema_version=3,
        input_sha256="x",
        title="Book",
        source_path="source",
        blocks=[DocumentBlock(id="b", page_index=0, text="Some source.")],
        chapters=[
            Chapter(
                id="c",
                number=1,
                title="One",
                start_block=0,
                end_block=1,
                confidence=1,
                manually_approved=True,
            )
        ],
    )
    path = tmp_path / "manifest.json"
    write_manifest(path, manifest)
    render_chapter_texts(manifest, tmp_path)
    (tmp_path / "chapters" / "001.txt").write_text("[[voice:Bella]]\n", encoding="utf-8")
    selection = prepare_chapter_selection(path, manifest, Settings())
    assert [chapter.number for chapter in selection.skipped] == [1]
    assert "empty_chapter" in manifest.review_required


def test_cleanup_failure_leaves_transaction_for_idempotent_recovery(tmp_path: Path, monkeypatch):
    from pathlib import Path as ConcretePath

    manifest = BookManifest(
        schema_version=3,
        input_sha256="x",
        title="Book",
        source_path="source",
        blocks=[DocumentBlock(id="b", page_index=0, text="Body")],
        chapters=[
            Chapter(id="c", number=1, title="Before", start_block=0, end_block=1, confidence=1)
        ],
    )
    path = tmp_path / "manifest.json"
    write_manifest(path, manifest)
    render_chapter_texts(manifest, tmp_path)
    updates = _updates(manifest)
    updates[0]["title"] = "After"
    original = ConcretePath.unlink

    def fail_journal(target, *args, **kwargs):
        if target == tmp_path / JOURNAL:
            raise OSError("cleanup failure")
        return original(target, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(ConcretePath, "unlink", fail_journal)
        with pytest.raises(ReviewRecoveryRequired):
            save_chapter_updates(path, updates)
        assert (tmp_path / JOURNAL).exists()
    assert read_manifest(path).chapters[0].title == "After"
    assert read_manifest(path).chapters[0].title == "After"
    assert not (tmp_path / JOURNAL).exists()


def test_committed_transaction_recovers_in_fresh_process(tmp_path: Path, monkeypatch):
    import subprocess
    import sys

    from pdf2audiobook import review_transaction

    manifest = BookManifest(
        schema_version=3,
        input_sha256="x",
        title="Book",
        source_path="source",
        blocks=[DocumentBlock(id="b", page_index=0, text="Body")],
        chapters=[
            Chapter(id="c", number=1, title="Before", start_block=0, end_block=1, confidence=1)
        ],
    )
    path = tmp_path / "manifest.json"
    write_manifest(path, manifest)
    render_chapter_texts(manifest, tmp_path)
    updates = _updates(manifest)
    updates[0]["title"] = "After"
    original = review_transaction.atomic_write

    def fail_manifest(target, data):
        if target == path:
            raise OSError("simulated failure")
        original(target, data)

    with monkeypatch.context() as patch:
        patch.setattr(review_transaction, "atomic_write", fail_manifest)
        with pytest.raises(ReviewRecoveryRequired):
            save_chapter_updates(path, updates)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; from pdf2audiobook.workspace import read_manifest; import sys; print(read_manifest(Path(sys.argv[1])).chapters[0].title)",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert result.stdout.strip() == "After"
    assert not (tmp_path / JOURNAL).exists()


@pytest.mark.parametrize("policy", ["warn", "inline", "end", "omit"])
def test_footnote_policy_survives_analyze_review_and_convert(
    tmp_path: Path, policy: str, monkeypatch
):
    import hashlib
    import json

    source = tmp_path / "notes.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((55, 100), "Chapter 1", fontsize=15)
    page.insert_text((55, 140), "A paragraph with a note reference.1", fontsize=12)
    page.insert_text((55, 180), "Another ordinary paragraph.", fontsize=12)
    page.insert_text((55, 745), "1 A separate footnote.", fontsize=7)
    doc.save(source)
    doc.close()
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.llm.enabled = False
    settings.pdf.ocr = "never"
    settings.pdf.footnotes = policy
    settings.chapters.allow_single_chapter = True
    path = analyze_book(source, settings)
    manifest = read_manifest(path)
    assert any(block.kind == "footnote" for block in manifest.blocks)
    text_path = path.parent / "chapters" / "001.txt"
    expected = text_path.read_text(encoding="utf-8")
    save_chapter_updates(path, _updates(manifest))
    assert text_path.read_text(encoding="utf-8") == expected

    class Provider:
        sample_rate = 24000
        max_chars_per_chunk = 350

        def generate(self, text, *, voice, speed):
            return np.ones(240, dtype=np.float32) * 0.1

    def encode(_samples, _rate, target, **_kwargs):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"synthetic audio")

    outputs = convert_book(source, settings, tts_provider=Provider(), encoder=encode)
    record = json.loads(outputs[0].with_suffix(".cache.json").read_text())
    assert record["rendering_inputs"] == {"footnotes": policy}
    assert record["text_sha256"] == hashlib.sha256(expected.encode()).hexdigest()
    from pdf2audiobook.cli import app

    monkeypatch.setattr("pdf2audiobook.audio.encode_m4b", lambda *_a, **_k: tmp_path / "book.m4b")
    result = CliRunner().invoke(
        app, ["pack-m4b", str(path), "--output", str(tmp_path / "book.m4b"), "--no-config"]
    )
    assert result.exit_code == 0, result.stderr


def test_review_boundary_conflict_preserves_edits_and_manifest(tmp_path: Path):
    from pdf2audiobook.errors import ExtractionError

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
    target = tmp_path / "chapters" / "001.txt"
    target.write_text("Private hand edit.", encoding="utf-8")
    before = path.read_bytes()
    updates = _updates(manifest)
    updates[0]["end_block"] = 2
    updates[1]["start_block"] = 2
    with pytest.raises(ExtractionError, match="Chapter 1 text conflicts") as exc:
        save_chapter_updates(path, updates)
    assert "Private hand edit" not in str(exc.value)
    assert path.read_bytes() == before
    assert target.read_text() == "Private hand edit."
    assert not (tmp_path / JOURNAL).exists()


def test_review_refuses_manifest_changed_between_read_and_commit(tmp_path: Path, monkeypatch):
    from pdf2audiobook import chapter_artifacts
    from pdf2audiobook.errors import ExtractionError

    manifest = BookManifest(
        schema_version=3,
        input_sha256="x",
        title="Book",
        source_path="source",
        blocks=[DocumentBlock(id="b", page_index=0, text="Body")],
        chapters=[
            Chapter(id="c", number=1, title="Before", start_block=0, end_block=1, confidence=1)
        ],
    )
    path = tmp_path / "manifest.json"
    write_manifest(path, manifest)
    render_chapter_texts(manifest, tmp_path)
    updates = _updates(manifest)
    updates[0]["title"] = "After"
    original = chapter_artifacts.plan_chapter_artifacts

    def mutate(*args, **kwargs):
        plan = original(*args, **kwargs)
        changed = manifest.model_copy(deep=True)
        changed.title = "External change"
        write_manifest(path, changed)
        return plan

    monkeypatch.setattr(chapter_artifacts, "plan_chapter_artifacts", mutate)
    with pytest.raises(ExtractionError, match="Manifest changed during review"):
        save_chapter_updates(path, updates)
    assert read_manifest(path).title == "External change"
    assert not (tmp_path / JOURNAL).exists()


def test_approved_workspace_allows_policy_change_when_chapter_is_unedited(tmp_path: Path):
    source = tmp_path / "notes.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((55, 100), "Chapter 1", fontsize=15)
    page.insert_text((55, 140), "A paragraph with a note reference.1", fontsize=12)
    page.insert_text((55, 180), "Another ordinary paragraph.", fontsize=12)
    page.insert_text((55, 745), "1 A separate footnote.", fontsize=7)
    doc.save(source)
    doc.close()
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.llm.enabled = False
    settings.pdf.ocr = "never"
    path = analyze_book(source, settings)
    manifest = read_manifest(path)
    save_chapter_updates(path, _updates(manifest))
    settings.pdf.footnotes = "omit"
    assert analyze_book(source, settings) == path
    updated = read_manifest(path)
    assert updated.chapters[0].manually_approved
    assert "separate footnote" not in (path.parent / "chapters" / "001.txt").read_text()
    settings.pdf.footnotes = "inline"
    assert analyze_book(source, settings) == path
    assert "separate footnote" in (path.parent / "chapters" / "001.txt").read_text()
    assert read_manifest(path).chapters[0].manually_approved


def test_approved_workspace_policy_change_preserves_edited_chapter(tmp_path: Path):
    from pdf2audiobook.errors import ExtractionError

    source = tmp_path / "book.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Chapter 1")
    page.insert_text((72, 120), "Original narration.")
    doc.save(source)
    doc.close()
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.llm.enabled = False
    settings.pdf.ocr = "never"
    path = analyze_book(source, settings)
    save_chapter_updates(path, _updates(read_manifest(path)))
    chapter = path.parent / "chapters" / "001.txt"
    chapter.write_text("Private correction.\n", encoding="utf-8")
    before = path.read_bytes()
    settings.pdf.footnotes = "end"
    with pytest.raises(ExtractionError, match="Chapter 1 text conflicts"):
        analyze_book(source, settings)
    assert path.read_bytes() == before
    assert chapter.read_text() == "Private correction.\n"


def test_commit_record_sync_failure_is_reported_as_committed(tmp_path: Path, monkeypatch):
    from pdf2audiobook import review_transaction

    manifest = BookManifest(
        schema_version=3,
        input_sha256="x",
        title="Book",
        source_path="source",
        blocks=[DocumentBlock(id="b", page_index=0, text="Body")],
        chapters=[
            Chapter(id="c", number=1, title="Before", start_block=0, end_block=1, confidence=1)
        ],
    )
    path = tmp_path / "manifest.json"
    write_manifest(path, manifest)
    render_chapter_texts(manifest, tmp_path)
    updates = _updates(manifest)
    updates[0]["title"] = "After"
    with monkeypatch.context() as patch:
        patch.setattr(
            review_transaction,
            "_sync_directory",
            lambda _path: (_ for _ in ()).throw(OSError("failure")),
        )
        with pytest.raises(ReviewRecoveryRequired, match="committed"):
            save_chapter_updates(path, updates)
        assert (tmp_path / JOURNAL).exists()
    assert read_manifest(path).chapters[0].title == "After"
