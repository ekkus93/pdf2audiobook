"""Voice markers require chapter approval and known provider voices."""

import json
from pathlib import Path

import numpy as np
import pytest

import pdf2audiobook.pipeline as pipeline
from pdf2audiobook.config import Settings
from pdf2audiobook.errors import PartialConversionError
from pdf2audiobook.models import BookManifest, Chapter


class VoiceProvider:
    sample_rate = 24000
    max_chars_per_chunk = 350

    def __init__(self, voices):
        self.voices = voices
        self.calls = []

    def list_voices(self):
        return self.voices

    def generate(self, text, *, voice, speed):
        self.calls.append((text, voice))
        return np.full(24, 0.1, dtype=np.float32)


def _run(tmp_path: Path, monkeypatch, chapters: list[Chapter], texts: list[str], provider):
    manifest_path = tmp_path / "out" / "manifest.json"
    manifest = BookManifest(
        schema_version=3,
        input_sha256="a" * 64,
        title="Book",
        source_path="book.pdf",
        chapters=chapters,
    )
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.pdf.ocr = "never"
    settings.llm.enabled = False

    def render(_manifest, folder, *_args):
        for chapter, text in zip(chapters, texts, strict=True):
            path = folder / "chapters" / f"{chapter.number:03d}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def encode(_samples, _rate, output, **_kwargs):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"synthetic-mp3")

    monkeypatch.setattr(pipeline, "analyze_book", lambda *_args, **_kwargs: manifest_path)
    monkeypatch.setattr(pipeline, "read_manifest", lambda _path: manifest)
    monkeypatch.setattr(pipeline, "render_chapter_texts", render)
    monkeypatch.setattr(pipeline, "encode_mp3", encode)
    return pipeline.convert_book(
        tmp_path / "book.pdf", settings, tts_provider=provider
    ), manifest_path


def _chapter(number: int, *, approved: bool = False) -> Chapter:
    return Chapter(
        id=f"chapter-{number}",
        number=number,
        title=f"Chapter {number}",
        start_block=number - 1,
        end_block=number,
        confidence=1,
        manually_approved=approved,
    )


def test_unapproved_markers_fail_the_chapter_but_other_chapters_continue(tmp_path, monkeypatch):
    provider = VoiceProvider(["Jasper", "Known"])
    chapters = [_chapter(1), _chapter(2)]
    texts = ["Before.\n\n[[voice:Known]]\n\nAfter.", "Ordinary chapter prose."]
    with pytest.raises(PartialConversionError, match=r"chapter\(s\): 1") as raised:
        _run(tmp_path, monkeypatch, chapters, texts, provider)
    assert raised.value.exit_code == 7
    assert [voice for _text, voice in provider.calls] == ["Jasper"]
    status = json.loads((tmp_path / "out/reports/conversion_status.json").read_text())
    assert [(row["number"], row["status"]) for row in status["chapters"]] == [
        (1, "failed"),
        (2, "complete"),
    ]


def test_approved_marker_uses_its_voice_and_unknown_marker_fails_preflight(tmp_path, monkeypatch):
    provider = VoiceProvider(["Jasper", "Known"])
    chapter = _chapter(1, approved=True)
    result, _ = _run(
        tmp_path / "approved",
        monkeypatch,
        [chapter],
        ["Before.\n\n[[voice:Known]]\n\nAfter."],
        provider,
    )
    assert len(result) == 1
    assert [voice for _text, voice in provider.calls] == ["Jasper", "Known"]

    unknown_provider = VoiceProvider(["Jasper"])
    with pytest.raises(PartialConversionError, match=r"chapter\(s\): 1"):
        _run(
            tmp_path / "unknown",
            monkeypatch,
            [_chapter(1, approved=True)],
            ["Before.\n\n[[voice:Missing]]\n\nAfter."],
            unknown_provider,
        )
    assert unknown_provider.calls == []


def test_conversion_report_records_scene_break_pause_mapping(tmp_path, monkeypatch):
    provider = VoiceProvider(["Jasper"])
    _run(
        tmp_path / "pause",
        monkeypatch,
        [_chapter(1)],
        ["Before.\n\n* * *\n\nAfter."],
        provider,
    )
    status = json.loads((tmp_path / "pause/out/reports/conversion_status.json").read_text())
    assert status["pause_count"] == 1
    chapter = status["chapters"][0]
    assert chapter["pause_count"] == 1
    assert [row["kind"] for row in chapter["chunk_mapping"]].count("pause") == 1


def test_voice_listing_failure_fails_only_marked_chapter_privately(tmp_path, monkeypatch):
    class BrokenVoiceProvider(VoiceProvider):
        def list_voices(self):
            raise RuntimeError("PRIVATE PROVIDER DETAIL")

    provider = BrokenVoiceProvider(["Jasper"])
    with pytest.raises(PartialConversionError, match=r"chapter\(s\): 1"):
        _run(
            tmp_path,
            monkeypatch,
            [_chapter(1, approved=True), _chapter(2)],
            ["Before.\n\n[[voice:Known]]\n\nAfter.", "Ordinary prose."],
            provider,
        )
    assert [voice for _text, voice in provider.calls] == ["Jasper"]
    status = json.loads((tmp_path / "out/reports/conversion_status.json").read_text())
    assert status["chapters"][0]["reason_code"] == "voice_validation_failed"
    assert status["chapters"][1]["status"] == "complete"
