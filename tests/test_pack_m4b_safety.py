"""M4B packaging verifies current audio and conversion removes only owned files."""

import hashlib
import json
import shutil

import numpy as np
import pytest
from typer.testing import CliRunner

from pdf2audiobook.audio import audio_output_path, encode_mp3
from pdf2audiobook.cli import app
from pdf2audiobook.config import Settings
from pdf2audiobook.document.structure import render_chapter_texts
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock
from pdf2audiobook.pipeline import chapter_audio_fingerprint, convert_book
from pdf2audiobook.workspace import digest_bytes, write_manifest


def make_book(root):
    chapter = Chapter(
        id="chapter-private-id",
        number=1,
        title="Synthetic Chapter",
        start_block=0,
        end_block=1,
        confidence=1.0,
    )
    manifest = BookManifest(
        schema_version=3,
        input_sha256="synthetic",
        title="Synthetic Book",
        author="Synthetic Author",
        source_path="private-source.pdf",
        blocks=[DocumentBlock(id="p1", text="Narration.", page_index=0)],
        chapters=[chapter],
    )
    (root / "chapters").mkdir(parents=True)
    (root / "chapters" / "001.txt").write_text("Narration.", encoding="utf-8")
    manifest_path = root / "manifest.json"
    write_manifest(manifest_path, manifest)
    return manifest, chapter, manifest_path


def add_sidecar(path, manifest, chapter, settings, *, fingerprint=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(b"verified synthetic audio")
    payload = path.read_bytes()
    text = (path.parents[1] / "chapters" / f"{chapter.number:03d}.txt").read_text()
    identity = chapter_audio_fingerprint(text, settings, manifest, chapter)
    path.with_suffix(".cache.json").write_text(
        json.dumps(
            {
                "chapter_id": chapter.id,
                "sidecar_version": 2,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "fingerprint": identity if fingerprint is None else fingerprint,
                "bytes": len(payload),
                "sha256": digest_bytes(payload),
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg/ffprobe are required for M4B packaging acceptance",
)
def test_pack_m4b_cli_happy_path(tmp_path):
    settings = Settings()
    manifest, chapter, manifest_path = make_book(tmp_path)
    output = audio_output_path(manifest, chapter, tmp_path)
    rate = 24000
    samples = np.full(rate // 4, 0.01, dtype=np.float32)
    encode_mp3(
        samples,
        rate,
        output,
        bitrate=settings.tts.bitrate,
        target_rate=settings.tts.sample_rate,
        title=chapter.title,
        artist=manifest.author,
        album=manifest.title,
        track=chapter.number,
    )
    add_sidecar(output, manifest, chapter, settings)

    result = CliRunner().invoke(
        app,
        ["pack-m4b", str(manifest_path), "--output", str(tmp_path / "book.m4b"), "--no-config"],
    )
    assert result.exit_code == 0, result.stderr
    assert (tmp_path / "book.m4b").is_file()


def test_pack_m4b_cli_refuses_text_stale_audio_without_disclosing_content(tmp_path):
    settings = Settings()
    manifest, chapter, manifest_path = make_book(tmp_path)
    output = audio_output_path(manifest, chapter, tmp_path)
    add_sidecar(output, manifest, chapter, settings)
    sidecar = json.loads(output.with_suffix(".cache.json").read_text())
    sidecar["text_sha256"] = "stale-identity"
    output.with_suffix(".cache.json").write_text(json.dumps(sidecar))

    result = CliRunner().invoke(
        app,
        [
            "pack-m4b",
            str(manifest_path),
            "--output",
            str(tmp_path / "private-output.m4b"),
            "--no-config",
        ],
    )
    assert result.exit_code == 6
    assert "chapter(s): 1" in result.stderr
    for private in ("Narration", "private-source", "private-output", str(tmp_path)):
        assert private not in result.stderr


def test_boundary_edit_after_convert_makes_affected_chapter_audio_stale(tmp_path):
    first = Chapter(
        id="chapter-one", number=1, title="One", start_block=0, end_block=1, confidence=1.0
    )
    second = Chapter(
        id="chapter-two", number=2, title="Two", start_block=1, end_block=3, confidence=1.0
    )
    manifest = BookManifest(
        schema_version=3,
        input_sha256="synthetic",
        title="Synthetic Book",
        author="Synthetic Author",
        source_path="private-source.pdf",
        blocks=[
            DocumentBlock(id=f"p{i}", text=f"Narration {i}.", page_index=0) for i in range(1, 4)
        ],
        chapters=[first, second],
    )
    (tmp_path / "chapters").mkdir()
    (tmp_path / "chapters" / "001.txt").write_text("Narration 1.", encoding="utf-8")
    (tmp_path / "chapters" / "002.txt").write_text("Narration 2.\n\nNarration 3.", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    write_manifest(manifest_path, manifest)
    settings = Settings()
    for chapter in manifest.chapters:
        add_sidecar(audio_output_path(manifest, chapter, tmp_path), manifest, chapter, settings)

    # Change an approved boundary after audio conversion and rebuild the derived chapter text.
    first.end_block = 2
    second.start_block = 2
    write_manifest(manifest_path, manifest)
    render_chapter_texts(manifest, tmp_path)
    result = CliRunner().invoke(
        app,
        ["pack-m4b", str(manifest_path), "--output", str(tmp_path / "book.m4b"), "--no-config"],
    )

    assert result.exit_code == 6
    assert "chapter(s): 1, 2" in result.stderr
    assert "Narration" not in result.stderr
    assert str(tmp_path) not in result.stderr


def test_pack_m4b_ignores_conversion_settings_fingerprint(tmp_path, monkeypatch):
    settings = Settings()
    manifest, chapter, manifest_path = make_book(tmp_path)
    output = audio_output_path(manifest, chapter, tmp_path)
    add_sidecar(output, manifest, chapter, settings, fingerprint="voice-speed-cover-specific")
    monkeypatch.setattr("pdf2audiobook.audio.encode_m4b", lambda *_a, **_k: tmp_path / "book.m4b")
    result = CliRunner().invoke(
        app,
        ["pack-m4b", str(manifest_path), "--output", str(tmp_path / "book.m4b"), "--no-config"],
    )
    assert result.exit_code == 0, result.stderr


def test_cli_convert_with_voice_speed_cover_then_pack(tmp_path, monkeypatch):
    manifest, chapter, manifest_path = make_book(tmp_path)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"synthetic source")
    chapter_cover = tmp_path / "chapter.jpg"
    chapter_cover.write_bytes(b"\xff\xd8\xffchapter-cover")
    book_cover = tmp_path / "book.jpg"
    book_cover.write_bytes(b"\xff\xd8\xffbook-cover")
    observed = {}

    class StubKitten:
        sample_rate = 24000

        def __init__(self, _model):
            pass

    monkeypatch.setattr("pdf2audiobook.pipeline.analyze_book", lambda *_a, **_k: manifest_path)
    monkeypatch.setattr("pdf2audiobook.pipeline.read_manifest", lambda _path: manifest)
    monkeypatch.setattr("pdf2audiobook.pipeline.render_chapter_texts", lambda *_a, **_k: None)
    monkeypatch.setattr("pdf2audiobook.pipeline.KittenProvider", StubKitten)
    monkeypatch.setattr(
        "pdf2audiobook.pipeline.synthesize_chunks",
        lambda *_a, **kwargs: (
            observed.update(voice=kwargs["voice"], speed=kwargs["speed"])
            or np.ones(2400, dtype=np.float32)
        ),
    )

    def encode_mp3_stub(_samples, _rate, path, **kwargs):
        observed["chapter_cover"] = kwargs["cover_image"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic-mp3")
        return path

    monkeypatch.setattr("pdf2audiobook.pipeline.encode_mp3", encode_mp3_stub)
    converted = CliRunner().invoke(
        app,
        [
            "convert",
            str(source),
            "--no-config",
            "--voice",
            "Bella",
            "--speed",
            "1.25",
            "--cover",
            str(chapter_cover),
        ],
    )
    assert converted.exit_code == 0, converted.stderr
    assert observed == {
        "voice": "Bella",
        "speed": 1.25,
        "chapter_cover": (chapter_cover.read_bytes(), "image/jpeg"),
    }

    packed_cover = {}

    def encode_m4b_stub(_files, output, **kwargs):
        packed_cover.update(kwargs)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"m4b")
        return output

    monkeypatch.setattr("pdf2audiobook.audio.encode_m4b", encode_m4b_stub)
    packed = CliRunner().invoke(
        app,
        [
            "pack-m4b",
            str(manifest_path),
            "--output",
            str(tmp_path / "book.m4b"),
            "--cover",
            str(book_cover),
            "--no-config",
        ],
    )
    assert packed.exit_code == 0, packed.stderr
    assert packed_cover["cover_image"] == (book_cover.read_bytes(), "image/jpeg")


def test_convert_rename_removes_only_valid_same_chapter_audio(tmp_path, monkeypatch):
    settings = Settings()
    source = tmp_path / "source.pdf"
    source.write_bytes(b"placeholder")
    manifest, chapter, manifest_path = make_book(tmp_path)
    old_path = tmp_path / "audio" / "001 - Previous Title.mp3"
    add_sidecar(old_path, manifest, chapter, settings)
    unrelated = tmp_path / "audio" / "user-recording.mp3"
    unrelated.write_bytes(b"not owned")

    class StubKitten:
        sample_rate = 24000

        def __init__(self, _model):
            pass

    monkeypatch.setattr("pdf2audiobook.pipeline.analyze_book", lambda *a, **k: manifest_path)
    monkeypatch.setattr("pdf2audiobook.pipeline.read_manifest", lambda *_: manifest)
    monkeypatch.setattr("pdf2audiobook.pipeline.render_chapter_texts", lambda *_: None)
    monkeypatch.setattr("pdf2audiobook.pipeline.KittenProvider", StubKitten)
    monkeypatch.setattr(
        "pdf2audiobook.pipeline.synthesize_chunks",
        lambda *_a, **_k: np.full(2400, 0.01, dtype=np.float32),
    )

    def publish(_audio, _rate, target, **_metadata):
        target.write_bytes(b"new chapter audio")
        return target

    monkeypatch.setattr("pdf2audiobook.pipeline.encode_mp3", publish)
    outputs = convert_book(source, settings, force=True)

    assert outputs == [audio_output_path(manifest, chapter, tmp_path)]
    assert outputs[0].is_file()
    assert not old_path.exists()
    assert not old_path.with_suffix(".cache.json").exists()
    assert unrelated.read_bytes() == b"not owned"


def test_case_only_chapter_rename_does_not_unlink_current_audio(tmp_path, monkeypatch):
    settings = Settings()
    source = tmp_path / "source.pdf"
    source.write_bytes(b"placeholder")
    manifest, chapter, manifest_path = make_book(tmp_path)
    old_path = tmp_path / "audio" / "001 - Synthetic Chapter.mp3"
    add_sidecar(old_path, manifest, chapter, settings)
    chapter.title = "synthetic chapter"

    class StubKitten:
        sample_rate = 24000

        def __init__(self, _model):
            pass

    monkeypatch.setattr("pdf2audiobook.pipeline.analyze_book", lambda *a, **k: manifest_path)
    monkeypatch.setattr("pdf2audiobook.pipeline.read_manifest", lambda *_: manifest)
    monkeypatch.setattr("pdf2audiobook.pipeline.render_chapter_texts", lambda *_: None)
    monkeypatch.setattr("pdf2audiobook.pipeline.KittenProvider", StubKitten)
    monkeypatch.setattr(
        "pdf2audiobook.pipeline.synthesize_chunks",
        lambda *_a, **_k: np.full(2400, 0.01, dtype=np.float32),
    )
    monkeypatch.setattr(
        "pdf2audiobook.pipeline.encode_mp3",
        lambda _audio, _rate, target, **_metadata: target.write_bytes(b"new audio") or target,
    )
    monkeypatch.setattr(
        "pdf2audiobook.pipeline.os.path.samefile",
        lambda left, right: str(left).casefold() == str(right).casefold(),
    )

    outputs = convert_book(source, settings, force=True)
    assert outputs[0].is_file()
    assert outputs[0].name == "001 - synthetic chapter.mp3"
    assert old_path.is_file()
