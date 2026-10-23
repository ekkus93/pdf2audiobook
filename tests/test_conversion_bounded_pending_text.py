"""Chapter conversion retains bounded text and checks mid-conversion edits."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from pdf2audiobook import pipeline
from pdf2audiobook.config import Settings
from pdf2audiobook.errors import AudioError
from pdf2audiobook.models import BookManifest, Chapter


def _setup_conversion(tmp_path, monkeypatch, chapter_texts):
    source = tmp_path / "PRIVATE_SOURCE.pdf"
    root = tmp_path / "workspace"
    manifest_path = root / "manifest.json"
    chapters = [
        Chapter(
            id=f"chapter-{index}",
            number=index,
            title=f"Chapter {index}",
            start_block=index - 1,
            end_block=index,
            confidence=1.0,
        )
        for index in range(1, len(chapter_texts) + 1)
    ]
    manifest = BookManifest(
        input_sha256="synthetic",
        title="Synthetic book",
        source_path=str(source),
        chapters=chapters,
    )

    def render(_manifest, folder, *_args):
        directory = folder / "chapters"
        directory.mkdir(parents=True, exist_ok=True)
        for index, content in enumerate(chapter_texts, 1):
            (directory / f"{index:03d}.txt").write_text(content, encoding="utf-8")

    monkeypatch.setattr(pipeline, "analyze_book", lambda *_args, **_kw: manifest_path)
    monkeypatch.setattr(pipeline, "read_manifest", lambda *_args: manifest)
    monkeypatch.setattr(pipeline, "render_chapter_texts", render)
    monkeypatch.setattr(
        pipeline,
        "audio_output_path",
        lambda _manifest, chapter, _folder: root / "audio" / f"{chapter.number:03d}.mp3",
    )
    return source, Settings(), root


def test_multiple_chapters_render_in_order_without_retaining_pending_text(tmp_path, monkeypatch):
    source, settings, root = _setup_conversion(
        tmp_path,
        monkeypatch,
        ["First chapter.", "Second chapter.", "Third chapter."],
    )
    seen = []
    monkeypatch.setattr(
        pipeline,
        "KittenProvider",
        lambda *_args: SimpleNamespace(sample_rate=24000),
    )
    monkeypatch.setattr(
        pipeline,
        "synthesize_chunks",
        lambda text, *_args, **_kwargs: seen.append(text) or [0.0],
    )

    def encode(_samples, _rate, target, **_kwargs):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"synthetic MP3")

    monkeypatch.setattr(pipeline, "encode_mp3", encode)
    outputs = pipeline.convert_book(source, settings)
    assert outputs == [root / "audio" / f"{n:03d}.mp3" for n in (1, 2, 3)]
    assert seen == ["First chapter.", "Second chapter.", "Third chapter."]
    assert all(output.exists() for output in outputs)


def test_chapter_edit_between_preflight_and_synthesis_fails_closed(tmp_path, monkeypatch):
    source, settings, root = _setup_conversion(
        tmp_path,
        monkeypatch,
        ["Original approved chapter."],
    )
    chapter_file = root / "chapters" / "001.txt"
    original_read = Path.read_text
    reads = []

    def change_after_preflight(self, *args, **kwargs):
        if self == chapter_file:
            reads.append(1)
            if len(reads) == 2:
                return "Different prose after preflight."
        return original_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", change_after_preflight)
    monkeypatch.setattr(
        pipeline,
        "KittenProvider",
        lambda *_args: pytest.fail("TTS must not load for changed chapter text"),
    )
    with pytest.raises(AudioError, match="Approved chapter text changed") as exc:
        pipeline.convert_book(source, settings)
    assert len(reads) == 2
    assert "PRIVATE_SOURCE" not in str(exc.value)
    assert not (root / "audio").exists()
