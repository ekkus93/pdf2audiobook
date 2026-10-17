"""Pipeline cache selection without model downloads or external services."""

from types import SimpleNamespace

import numpy as np

import pdf2audiobook.pipeline as pipeline
from pdf2audiobook.config import Settings
from pdf2audiobook.models import BookManifest, Chapter


def test_mp3_resume_force_and_no_resume(tmp_path, monkeypatch):
    chapter = Chapter(id="c1", number=1, title="First", start_block=0, end_block=1, confidence=1)
    manifest = BookManifest(
        input_sha256="a" * 64, title="Book", source_path="book.pdf", chapters=[chapter]
    )
    path = tmp_path / "manifest.json"
    settings = Settings()
    calls = []

    def render(_manifest, folder):
        target = folder / "chapters" / "001.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("A sentence.", encoding="utf-8")

    def synthesize(*args, **kwargs):
        calls.append(kwargs["voice"])
        return np.ones(100, dtype=np.float32)

    def encode(samples, rate, output, **kwargs):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"fake-mp3")

    monkeypatch.setattr(pipeline, "analyze_book", lambda *_: path)
    monkeypatch.setattr(pipeline, "read_manifest", lambda _: manifest)
    monkeypatch.setattr(pipeline, "render_chapter_texts", render)
    monkeypatch.setattr(pipeline, "KittenProvider", lambda _: SimpleNamespace(sample_rate=24000))
    monkeypatch.setattr(pipeline, "synthesize_chunks", synthesize)
    monkeypatch.setattr(pipeline, "encode_mp3", encode)
    monkeypatch.setattr(
        "mutagen.mp3.MP3", lambda _: SimpleNamespace(info=SimpleNamespace(length=1))
    )

    pipeline.convert_book(tmp_path / "book.pdf", settings)
    pipeline.convert_book(tmp_path / "book.pdf", settings)
    assert len(calls) == 1
    pipeline.convert_book(tmp_path / "book.pdf", settings, force=True)
    assert len(calls) == 2
    disabled = settings.model_copy(update={
        "general": settings.general.model_copy(update={"resume": False})
    })
    pipeline.convert_book(tmp_path / "book.pdf", disabled)
    assert len(calls) == 3
    changed = settings.model_copy(update={
        "tts": settings.tts.model_copy(update={
            "kitten": settings.tts.kitten.model_copy(update={"voice": "OtherVoice"})
        })
    })
    pipeline.convert_book(tmp_path / "book.pdf", changed)
    assert calls == ["Jasper", "Jasper", "Jasper", "OtherVoice"]
