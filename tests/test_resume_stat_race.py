"""A transient cached MP3 stat failure must regenerate audio, not leak its path."""

import json
from pathlib import Path
from types import SimpleNamespace

from pdf2audiobook import pipeline
from pdf2audiobook.config import Settings
from pdf2audiobook.models import BookManifest, Chapter


def test_resume_recovers_from_output_stat_race_without_leaking_path(tmp_path, monkeypatch):
    source = tmp_path / "PRIVATE_BOOK_TITLE.pdf"
    root = tmp_path / "workspace"
    root.mkdir()
    manifest_path = root / "manifest.json"
    chapter = Chapter(
        id="chapter-one",
        number=1,
        title="Chapter One",
        start_block=0,
        end_block=1,
        confidence=1.0,
    )
    manifest = BookManifest(
        input_sha256="synthetic",
        title="Synthetic book",
        source_path=str(source),
        chapters=[chapter],
    )
    output = root / "audio" / "PRIVATE_BOOK_TITLE.mp3"
    output.parent.mkdir()
    output.write_bytes(b"old cached MP3")
    record = output.with_suffix(".cache.json")
    record.write_text('{"fingerprint":"stale"}', encoding="utf-8")
    settings = Settings()

    def render(_manifest, folder, *_args):
        (folder / "chapters").mkdir(exist_ok=True)
        (folder / "chapters" / "001.txt").write_text("Speak this", encoding="utf-8")

    monkeypatch.setattr(pipeline, "analyze_book", lambda *args, **_kw: manifest_path)
    monkeypatch.setattr(pipeline, "read_manifest", lambda *_args: manifest)
    monkeypatch.setattr(pipeline, "render_chapter_texts", render)
    monkeypatch.setattr(pipeline, "audio_output_path", lambda *_args: output)
    monkeypatch.setattr(
        pipeline,
        "KittenProvider",
        lambda *_args: SimpleNamespace(sample_rate=24000),
    )
    syntheses = []
    monkeypatch.setattr(
        pipeline,
        "synthesize_chunks",
        lambda text, *_args, **_kwargs: syntheses.append(text) or [0.0],
    )

    def encode(_samples, _rate, target, **_kwargs):
        target.write_bytes(b"regenerated MP3")

    monkeypatch.setattr(pipeline, "encode_mp3", encode)
    original_stat = Path.stat
    original_is_file = Path.is_file
    fail_once = {"pending": True}

    def is_file(self):
        if self == output:
            return True
        return original_is_file(self)

    def stat(self, *args, **kwargs):
        if self == output and fail_once["pending"]:
            fail_once["pending"] = False
            raise OSError("PRIVATE_BOOK_TITLE.mp3: temporary stat failure")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_file", is_file)
    monkeypatch.setattr(Path, "stat", stat)

    assert pipeline.convert_book(source, settings) == [output]
    assert fail_once["pending"] is False
    assert syntheses == ["Speak this"]
    assert output.read_bytes() == b"regenerated MP3"
    metadata = json.loads(record.read_text(encoding="utf-8"))
    assert metadata["bytes"] == len(b"regenerated MP3")
    assert len(metadata["sha256"]) == 64
