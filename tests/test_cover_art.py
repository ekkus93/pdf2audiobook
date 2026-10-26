"""Cover image validation, cache identity and embedded artwork contracts."""

import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from mutagen.id3 import ID3
from mutagen.mp4 import MP4
from typer.testing import CliRunner

from pdf2audiobook.audio import encode_m4b, encode_mp3, read_cover_image
from pdf2audiobook.cli import app
from pdf2audiobook.config import Settings
from pdf2audiobook.errors import ConfigError
from pdf2audiobook.models import BookManifest, Chapter
from pdf2audiobook.pipeline import chapter_audio_fingerprint, convert_book

JPEG = b"\xff\xd8\xffsynthetic-jpeg"
PNG = b"\x89PNG\r\n\x1a\nsynthetic-png"


@pytest.mark.parametrize(("data", "mime"), [(JPEG, "image/jpeg"), (PNG, "image/png")])
def test_cover_magic_byte_validation(tmp_path: Path, data: bytes, mime: str):
    path = tmp_path / "cover.img"
    path.write_bytes(data)
    assert read_cover_image(path) == (data, mime)


@pytest.mark.parametrize("data", [b"not an image", b"\xff\xd8", b"\x89PNG\r\n"])
def test_invalid_cover_is_rejected_without_private_path(tmp_path: Path, data: bytes):
    private_path = tmp_path / "PRIVATE_COVER_PATH"
    private_path.write_bytes(data)
    with pytest.raises(ConfigError) as error:
        read_cover_image(private_path)
    assert "PRIVATE_COVER_PATH" not in str(error.value)


def test_oversized_cover_is_rejected(tmp_path: Path):
    path = tmp_path / "large.png"
    path.write_bytes(PNG + b"x" * (5 * 1024 * 1024))
    with pytest.raises(ConfigError, match="5 MiB"):
        read_cover_image(path)


@pytest.mark.parametrize("data", [JPEG, PNG])
def test_chapter_mp3_and_m4b_embed_cover(data: bytes, tmp_path: Path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg unavailable")
    mime = "image/jpeg" if data.startswith(b"\xff\xd8\xff") else "image/png"
    source = tmp_path / "chapter.mp3"
    encode_mp3(
        np.ones(2400, dtype=np.float32) * 0.02,
        24000,
        source,
        bitrate="96k",
        target_rate=24000,
        title="Chapter",
        artist="Author",
        album="Book",
        track=1,
        cover_image=(data, mime),
    )
    frames = ID3(source).getall("APIC")
    assert len(frames) == 1
    assert frames[0].data == data
    m4b = tmp_path / "book.m4b"
    encode_m4b([(source, "Chapter")], m4b, title="Book", artist="Author", cover_image=(data, mime))
    assert bytes(MP4(m4b).tags["covr"][0]) == data


def test_cover_is_read_and_hashed_once_per_conversion_run(tmp_path: Path, monkeypatch):
    source = tmp_path / "book.pdf"
    manifest_path = tmp_path / "out" / "manifest.json"
    chapters = [
        Chapter(
            id=f"c{number}",
            number=number,
            title=f"Chapter {number}",
            start_block=number - 1,
            end_block=number,
            confidence=1,
        )
        for number in (1, 2)
    ]
    manifest = BookManifest(
        schema_version=3,
        input_sha256="a" * 64,
        title="Book",
        source_path="book.pdf",
        chapters=chapters,
    )
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.llm.enabled = False
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(JPEG)
    settings.audio.cover_image = str(cover)

    def render(_manifest, folder, *_args):
        for chapter in chapters:
            text_path = folder / "chapters" / f"{chapter.number:03d}.txt"
            text_path.parent.mkdir(parents=True, exist_ok=True)
            text_path.write_text(f"Sentence for chapter {chapter.number}.", encoding="utf-8")

    embedded_covers = []

    def encode(_samples, _rate, output, **kwargs):
        embedded_covers.append(kwargs["cover_image"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"fake-mp3")

    def synthesize(*_args, **_kwargs):
        cover.write_bytes(b"\xff\xd8\xffchanged-after-fingerprint")
        return np.ones(100)

    from pdf2audiobook import pipeline

    read_calls = []
    hash_calls = []
    original_read = pipeline.read_cover_image
    original_digest = pipeline.digest_bytes

    def counted_read(path):
        read_calls.append(path)
        return original_read(path)

    def counted_digest(data):
        if data == JPEG:
            hash_calls.append(data)
        return original_digest(data)

    monkeypatch.setattr(pipeline, "read_cover_image", counted_read)
    monkeypatch.setattr(pipeline, "digest_bytes", counted_digest)
    monkeypatch.setattr(pipeline, "analyze_book", lambda *_a, **_k: manifest_path)
    monkeypatch.setattr(pipeline, "read_manifest", lambda _p: manifest)
    monkeypatch.setattr(pipeline, "render_chapter_texts", render)
    monkeypatch.setattr(
        pipeline, "KittenProvider", lambda _model: SimpleNamespace(sample_rate=24000)
    )
    monkeypatch.setattr(pipeline, "synthesize_chunks", synthesize)
    monkeypatch.setattr(pipeline, "encode_mp3", encode)
    monkeypatch.setattr(
        "mutagen.mp3.MP3",
        lambda _path, ID3=None: SimpleNamespace(
            info=SimpleNamespace(length=1),
            tags={
                "title": ["Chapter"],
                "album": ["Book"],
                "tracknumber": ["1"],
                "artist": ["Author"],
            },
        ),
    )

    convert_book(source, settings)
    assert read_calls == [str(cover)]
    assert hash_calls == [JPEG]
    assert embedded_covers == [(JPEG, "image/jpeg"), (JPEG, "image/jpeg")]


def test_cover_bytes_change_fingerprint_and_regenerate_mp3(tmp_path: Path, monkeypatch):
    source = tmp_path / "book.pdf"
    manifest_path = tmp_path / "out" / "manifest.json"
    chapter = Chapter(id="c1", number=1, title="First", start_block=0, end_block=1, confidence=1)
    manifest = BookManifest(
        schema_version=3,
        input_sha256="a" * 64,
        title="Book",
        source_path="book.pdf",
        chapters=[chapter],
    )
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.llm.enabled = False
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(JPEG)
    settings.audio.cover_image = str(cover)
    before = chapter_audio_fingerprint("A sentence.", settings, manifest, chapter)
    calls = []

    def render(_manifest, folder, *_args):
        text_path = folder / "chapters" / "001.txt"
        text_path.parent.mkdir(parents=True, exist_ok=True)
        text_path.write_text("A sentence.", encoding="utf-8")

    def synthesize(*_args, **_kwargs):
        calls.append("synthesis")
        return np.ones(100, dtype=np.float32)

    def encode(_samples, _rate, output, **_kwargs):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"fake-mp3")

    monkeypatch.setattr("pdf2audiobook.pipeline.analyze_book", lambda *_a, **_k: manifest_path)
    monkeypatch.setattr("pdf2audiobook.pipeline.read_manifest", lambda _p: manifest)
    monkeypatch.setattr("pdf2audiobook.pipeline.render_chapter_texts", render)
    monkeypatch.setattr(
        "pdf2audiobook.pipeline.KittenProvider", lambda _model: SimpleNamespace(sample_rate=24000)
    )
    monkeypatch.setattr("pdf2audiobook.pipeline.synthesize_chunks", synthesize)
    monkeypatch.setattr("pdf2audiobook.pipeline.encode_mp3", encode)
    monkeypatch.setattr(
        "mutagen.mp3.MP3",
        lambda _path, ID3=None: SimpleNamespace(
            info=SimpleNamespace(length=1),
            tags={
                "title": ["First"],
                "album": ["Book"],
                "tracknumber": ["1"],
                "artist": ["Author"],
            },
        ),
    )
    convert_book(source, settings)
    cover.write_bytes(b"\xff\xd8\xffchanged-image")
    after = chapter_audio_fingerprint("A sentence.", settings, manifest, chapter)
    assert after != before
    convert_book(source, settings)
    assert calls == ["synthesis", "synthesis"]


@pytest.mark.parametrize("data", [b"invalid", PNG + b"x" * (5 * 1024 * 1024)])
def test_convert_rejects_invalid_cover_before_conversion(tmp_path: Path, data: bytes, monkeypatch):
    path = tmp_path / "PRIVATE_COVER_PATH.png"
    path.write_bytes(data)
    invoked = False

    def fake_convert(*_args, **_kwargs):
        nonlocal invoked
        invoked = True
        return []

    monkeypatch.setattr("pdf2audiobook.pipeline.convert_book", fake_convert)
    result = CliRunner().invoke(
        app,
        ["convert", str(tmp_path / "book.pdf"), "--no-config", "--cover", str(path)],
    )
    assert result.exit_code == 2
    assert "PRIVATE_COVER_PATH" not in result.output
    assert invoked is False
