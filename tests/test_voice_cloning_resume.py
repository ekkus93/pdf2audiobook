"""Offline regressions for reference rehydration during warm synthesis."""

import json
import socket
from types import SimpleNamespace

import pytest
from test_voice_cloning_conversion import app, runner
from test_voice_cloning_conversion import cloned_book as cloned_book

from pdf2audiobook.verification.models import SPECS


def without_transcript(book):
    args = book["args"].copy()
    start = args.index("--reference-text-file")
    del args[start : start + 2]
    return args


def identities(book):
    return {
        path.name: json.loads(path.read_text())["rendering_inputs"]["voice_clone"]
        for path in (book["manifest"].parent / "audio").glob("*.cache.json")
    }


def changed_chapter(monkeypatch):
    import pdf2audiobook.pipeline as pipeline

    original = pipeline.render_chapter_texts

    def render(manifest, folder, *args, **kwargs):
        result = original(manifest, folder, *args, **kwargs)
        path = folder / "chapters/002.txt"
        path.write_text(path.read_text() + "\nThe keeper returned with the key.")
        return result

    monkeypatch.setattr(pipeline, "render_chapter_texts", render)


@pytest.mark.parametrize("trigger", ["speed", "chapter"])
def test_warm_resume_rehydrates_same_transcript_without_changing_identity(
    cloned_book, monkeypatch, trigger
):
    book = cloned_book
    before = identities(book)
    text = book["text"].read_text()
    seen = []

    def transcribe(path):
        assert path.is_file() and path != book["audio"]
        seen.append(path)
        return text, {"model": SPECS["whisper"].revision, "package": "test"}

    monkeypatch.setattr("pdf2audiobook.tts.worker_client.transcribe_reference", transcribe)
    args = without_transcript(book)
    if trigger == "speed":
        args += ["--speed", "1.25"]
    else:
        changed_chapter(monkeypatch)
    calls = len(book["calls"])
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert len(seen) == 1 and not seen[0].exists()
    assert len(book["calls"]) > calls
    assert identities(book) == before
    assert "PRIVATE" not in result.output


def test_changed_auto_transcript_regenerates_and_records_reason(cloned_book, monkeypatch):
    book = cloned_book
    before = identities(book)
    monkeypatch.setattr(
        "pdf2audiobook.tts.worker_client.transcribe_reference",
        lambda path: (
            "Different PRIVATE reference words.",
            {"model": SPECS["whisper"].revision, "package": "test"},
        ),
    )
    changed_chapter(monkeypatch)
    calls = len(book["calls"])
    result = runner.invoke(app, without_transcript(book))
    assert result.exit_code == 0, result.output
    after = identities(book)
    assert all(
        after[name]["reference_text_sha256"] != value["reference_text_sha256"]
        for name, value in before.items()
    )
    # A changed reference transcript invalidates chapter 1 too, although only chapter 2 changed.
    assert len(book["calls"]) - calls >= calls
    report = json.loads((book["manifest"].parent / "reports/conversion_status.json").read_text())
    assert all(row["reason_code"] == "voice_reference_changed" for row in report["chapters"])
    assert "PRIVATE" not in result.output
    assert "Different PRIVATE" not in str(report)


def test_missing_asr_on_warm_resume_never_starts_a_worker_or_downloads(cloned_book, monkeypatch):
    from pdf2audiobook.tts import worker_client

    book = cloned_book
    before = identities(book)
    monkeypatch.setattr(
        "pdf2audiobook.verification.models.readiness", lambda *a: SimpleNamespace(ready=False)
    )
    monkeypatch.setattr(worker_client, "WorkerClient", lambda: pytest.fail("model worker loaded"))
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("implicit download"))
    calls = len(book["calls"])
    result = runner.invoke(app, without_transcript(book) + ["--speed", "1.25"])
    assert result.exit_code == 6, result.output
    assert "--reference-text-file" in result.output and "voice_clone_unavailable" in result.output
    assert "PRIVATE" not in result.output
    assert len(book["calls"]) == calls
    assert identities(book) == before
