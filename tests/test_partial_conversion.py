"""Failed chapter synthesis is isolated and resumes without rebuilding good MP3s."""

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import pdf2audiobook.pipeline as pipeline
from pdf2audiobook.config import Settings
from pdf2audiobook.errors import PartialConversionError
from pdf2audiobook.models import BookManifest, Chapter


class ChapterProvider:
    sample_rate = 24000
    max_chars_per_chunk = 350

    def __init__(self):
        self.fail_chapter_two = True
        self.calls: list[int] = []

    def generate(self, text, *, voice, speed):
        number = int(text.split("chapter ")[1].split()[0].rstrip("."))
        self.calls.append(number)
        if number == 2 and self.fail_chapter_two:
            raise RuntimeError("private source details")
        return np.ones(24, dtype=np.float32) * 0.1


def test_one_failed_chapter_continues_and_resume_only_regenerates_it(tmp_path, monkeypatch):
    source = tmp_path / "book.pdf"
    manifest_path = tmp_path / "out" / "manifest.json"
    chapters = [
        Chapter(
            id=f"chapter-{number}",
            number=number,
            title=f"Chapter {number}",
            start_block=number - 1,
            end_block=number,
            confidence=1,
        )
        for number in (1, 2, 3)
    ]
    manifest = BookManifest(
        schema_version=3,
        input_sha256="b" * 64,
        title="Book",
        source_path="book.pdf",
        chapters=chapters,
    )
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.pdf.ocr = "never"
    settings.llm.enabled = False
    settings.tts.max_retries = 0
    provider = ChapterProvider()

    def render(_manifest, folder, *_args):
        for chapter in chapters:
            path = folder / "chapters" / f"{chapter.number:03d}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"Narration for chapter {chapter.number}.", encoding="utf-8")

    def encode(_samples, _rate, output, **_kwargs):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(f"synthetic-mp3-{output.name}".encode())

    monkeypatch.setattr(pipeline, "analyze_book", lambda *_args, **_kwargs: manifest_path)
    monkeypatch.setattr(pipeline, "read_manifest", lambda _path: manifest)
    monkeypatch.setattr(pipeline, "render_chapter_texts", render)
    monkeypatch.setattr(pipeline, "encode_mp3", encode)
    logged_events = []
    monkeypatch.setattr(
        pipeline,
        "log_event",
        lambda event, **fields: logged_events.append((event, fields)),
    )

    def fake_mp3(path, ID3=None):
        title = Path(path).stem.split(" - ", 1)[1]
        number = int(title.split()[1])
        return SimpleNamespace(
            info=SimpleNamespace(length=1),
            tags={"title": [title], "album": ["Book"], "tracknumber": [str(number)]},
        )

    monkeypatch.setattr("mutagen.mp3.MP3", fake_mp3)

    with pytest.raises(PartialConversionError, match=r"chapter\(s\): 2") as raised:
        pipeline.convert_book(source, settings, tts_provider=provider)
    assert raised.value.exit_code == 7
    assert "private source details" not in str(raised.value)
    audio_dir = tmp_path / "out" / "audio"
    files = sorted(audio_dir.glob("*.mp3"))
    assert len(files) == 2
    assert ["Chapter 1" in path.name or "Chapter 3" in path.name for path in files] == [True, True]
    status = json.loads((tmp_path / "out/reports/conversion_status.json").read_text())
    assert [row["status"] for row in status["chapters"]] == ["complete", "failed", "complete"]
    assert any(
        event == "degraded_output" and fields.get("level") == logging.WARNING
        for event, fields in logged_events
    )

    provider.fail_chapter_two = False
    outputs = pipeline.convert_book(source, settings, tts_provider=provider)
    assert len(outputs) == 3
    assert provider.calls == [1, 2, 3, 2]
    status = json.loads((tmp_path / "out/reports/conversion_status.json").read_text())
    assert [row["status"] for row in status["chapters"]] == ["complete"] * 3


def test_keyboard_interrupt_removes_temporary_chapter_wav(tmp_path, monkeypatch):
    source = tmp_path / "book.pdf"
    manifest_path = tmp_path / "out" / "manifest.json"
    chapter = Chapter(
        id="chapter-1", number=1, title="Chapter 1", start_block=0, end_block=1, confidence=1
    )
    manifest = BookManifest(
        schema_version=3,
        input_sha256="c" * 64,
        title="Book",
        source_path="book.pdf",
        chapters=[chapter],
    )
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.pdf.ocr = "never"
    settings.llm.enabled = False
    stale_dir = tmp_path / "out/.cache/tts/chapters"
    stale_dir.mkdir(parents=True)
    (stale_dir / "chapter-stale.wav").write_bytes(b"stale")

    def render(_manifest, folder, *_args):
        path = folder / "chapters" / "001.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Narration text.", encoding="utf-8")

    monkeypatch.setattr(pipeline, "analyze_book", lambda *_args, **_kwargs: manifest_path)
    monkeypatch.setattr(pipeline, "read_manifest", lambda _path: manifest)
    monkeypatch.setattr(pipeline, "render_chapter_texts", render)
    monkeypatch.setattr(
        pipeline,
        "synthesize_chunks",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        pipeline.convert_book(source, settings, tts_provider=ChapterProvider())
    assert list(stale_dir.glob("chapter-*.wav")) == []
