"""pack-m4b checks freshness against the effective chapter text."""

import hashlib
import json
import shutil

import numpy as np
import pytest
from typer.testing import CliRunner

from pdf2audiobook.audio import audio_output_path, encode_mp3
from pdf2audiobook.cli import app
from pdf2audiobook.config import Settings
from pdf2audiobook.document.structure import render_chapter_narration, render_chapter_texts
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock
from pdf2audiobook.pipeline import chapter_audio_fingerprint, convert_book
from pdf2audiobook.workspace import digest_bytes, write_manifest


def make_book(root, *, chapters=1, blocks=1):
    items = [
        Chapter(
            id=f"chapter-{index}",
            number=index,
            title=f"Chapter {index}",
            start_block=index - 1,
            end_block=index if index < chapters else blocks,
            confidence=1.0,
        )
        for index in range(1, chapters + 1)
    ]
    manifest = BookManifest(
        schema_version=3,
        input_sha256="synthetic",
        title="Synthetic Book",
        author="Synthetic Author",
        source_path="private-source.pdf",
        blocks=[
            DocumentBlock(id=f"p{i}", text=f"Narration {i}.", page_index=0)
            for i in range(1, blocks + 1)
        ],
        chapters=items,
    )
    manifest_path = root / "manifest.json"
    write_manifest(manifest_path, manifest)
    render_chapter_texts(manifest, root)
    return manifest, manifest_path


def add_sidecar(manifest, chapter, root, settings, *, fingerprint=None):
    path = audio_output_path(manifest, chapter, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(b"verified synthetic audio")
    payload = path.read_bytes()
    text = render_chapter_narration(manifest, chapter)
    identity = chapter_audio_fingerprint(text, settings, manifest, chapter)
    path.with_suffix(".cache.json").write_text(
        json.dumps(
            {
                "chapter_id": chapter.id,
                "sidecar_version": 3,
                "rendering_inputs": {"footnotes": settings.pdf.footnotes},
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "fingerprint": identity if fingerprint is None else fingerprint,
                "bytes": len(payload),
                "sha256": digest_bytes(payload),
            }
        ),
        encoding="utf-8",
    )


def test_boundary_edited_in_the_manifest_only_makes_audio_stale(tmp_path, monkeypatch):
    manifest, manifest_path = make_book(tmp_path, chapters=2, blocks=3)
    settings = Settings()
    for chapter in manifest.chapters:
        add_sidecar(manifest, chapter, tmp_path, settings)
    monkeypatch.setattr("pdf2audiobook.audio.encode_m4b", lambda *_a, **_k: tmp_path / "x.m4b")

    # Hand-edit boundaries in manifest.json; chapters/*.txt are left as they were.
    first, second = manifest.chapters
    first.end_block = 2
    second.start_block = 2
    write_manifest(manifest_path, manifest)
    result = CliRunner().invoke(
        app,
        ["pack-m4b", str(manifest_path), "--output", str(tmp_path / "book.m4b"), "--no-config"],
    )
    assert result.exit_code == 6, result.stderr
    assert "chapter(s): 1, 2" in result.stderr
    assert "Narration" not in result.stderr
    assert str(tmp_path) not in result.stderr


def test_pack_rejects_audio_for_a_changed_chapter_text_file(tmp_path, monkeypatch):
    manifest, manifest_path = make_book(tmp_path)
    add_sidecar(manifest, manifest.chapters[0], tmp_path, Settings())
    (tmp_path / "chapters" / "001.txt").write_text("Something else entirely.", encoding="utf-8")
    monkeypatch.setattr("pdf2audiobook.audio.encode_m4b", lambda *_a, **_k: tmp_path / "x.m4b")
    result = CliRunner().invoke(
        app,
        ["pack-m4b", str(manifest_path), "--output", str(tmp_path / "book.m4b"), "--no-config"],
    )
    assert result.exit_code == 6
    assert "chapter(s): 1" in result.stderr


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg/ffprobe are required for M4B packaging acceptance",
)
def test_pack_m4b_cli_happy_path(tmp_path):
    settings = Settings()
    manifest, manifest_path = make_book(tmp_path)
    chapter = manifest.chapters[0]
    output = audio_output_path(manifest, chapter, tmp_path)
    samples = np.full(24000 // 4, 0.01, dtype=np.float32)
    encode_mp3(
        samples,
        24000,
        output,
        bitrate=settings.tts.bitrate,
        target_rate=settings.tts.sample_rate,
        title=chapter.title,
        artist=manifest.author,
        album=manifest.title,
        track=chapter.number,
    )
    add_sidecar(manifest, chapter, tmp_path, settings)
    result = CliRunner().invoke(
        app,
        ["pack-m4b", str(manifest_path), "--output", str(tmp_path / "book.m4b"), "--no-config"],
    )
    assert result.exit_code == 0, result.stderr
    assert (tmp_path / "book.m4b").is_file()


def test_pack_m4b_ignores_conversion_settings_fingerprint(tmp_path, monkeypatch):
    manifest, manifest_path = make_book(tmp_path)
    add_sidecar(
        manifest,
        manifest.chapters[0],
        tmp_path,
        Settings(),
        fingerprint="voice-speed-cover-specific",
    )
    monkeypatch.setattr("pdf2audiobook.audio.encode_m4b", lambda *_a, **_k: tmp_path / "book.m4b")
    result = CliRunner().invoke(
        app,
        ["pack-m4b", str(manifest_path), "--output", str(tmp_path / "book.m4b"), "--no-config"],
    )
    assert result.exit_code == 0, result.stderr


def test_convert_omit_footnotes_then_pack_without_config_uses_sidecar_inputs(tmp_path, monkeypatch):
    import pdf2audiobook.pipeline as pipeline

    source = tmp_path / "source.pdf"
    source.write_bytes(b"synthetic")
    manifest, manifest_path = make_book(tmp_path)
    manifest.blocks[0].kind = "unknown"
    manifest.blocks.append(
        DocumentBlock(id="note", text="Footnote.", page_index=0, kind="footnote")
    )
    manifest.chapters[0].end_block = 2
    write_manifest(manifest_path, manifest)
    settings = Settings()
    settings.general.output_dir = str(tmp_path)
    settings.pdf.footnotes = "omit"

    class StubProvider:
        sample_rate = 24000

    def synthesize(*_args, **_kwargs):
        return np.ones(100, dtype=np.float32)

    def encode(_samples, _rate, output, **_kwargs):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"converted audio")

    monkeypatch.setattr(pipeline, "analyze_book", lambda *_args, **_kwargs: manifest_path)
    monkeypatch.setattr(pipeline, "synthesize_chunks", synthesize)
    monkeypatch.setattr(
        "pdf2audiobook.audio.encode_m4b", lambda *_args, **_kwargs: tmp_path / "book.m4b"
    )

    outputs = convert_book(source, settings, tts_provider=StubProvider(), encoder=encode)
    assert len(outputs) == 1
    sidecar = json.loads(outputs[0].with_suffix(".cache.json").read_text(encoding="utf-8"))
    assert sidecar["rendering_inputs"] == {"footnotes": "omit"}
    result = CliRunner().invoke(
        app,
        ["pack-m4b", str(manifest_path), "--output", str(tmp_path / "book.m4b"), "--no-config"],
    )
    assert result.exit_code == 0, result.stderr


def test_pack_m4b_treats_v2_sidecar_as_stale(tmp_path, monkeypatch):
    manifest, manifest_path = make_book(tmp_path)
    output = audio_output_path(manifest, manifest.chapters[0], tmp_path)
    add_sidecar(manifest, manifest.chapters[0], tmp_path, Settings())
    record = output.with_suffix(".cache.json")
    sidecar = json.loads(record.read_text(encoding="utf-8"))
    sidecar["sidecar_version"] = 2
    sidecar.pop("rendering_inputs")
    record.write_text(json.dumps(sidecar), encoding="utf-8")
    monkeypatch.setattr(
        "pdf2audiobook.audio.encode_m4b", lambda *_args, **_kwargs: tmp_path / "x.m4b"
    )

    result = CliRunner().invoke(
        app,
        ["pack-m4b", str(manifest_path), "--output", str(tmp_path / "book.m4b"), "--no-config"],
    )

    assert result.exit_code == 6
    assert "chapter(s): 1" in result.stderr


def test_pack_omits_approved_empty_chapter_and_reports_its_number(tmp_path, monkeypatch):
    manifest, manifest_path = make_book(tmp_path, chapters=2, blocks=2)
    manifest.blocks[0].text = "* * *"
    manifest.review_required = ["empty_chapter"]
    manifest.chapters[0].manually_approved = True
    write_manifest(manifest_path, manifest)
    settings = Settings()
    add_sidecar(manifest, manifest.chapters[1], tmp_path, settings)
    packed_files = []
    monkeypatch.setattr(
        "pdf2audiobook.audio.encode_m4b",
        lambda files, output, **_kwargs: packed_files.extend(files) or output,
    )

    result = CliRunner().invoke(
        app,
        [
            "pack-m4b",
            str(manifest_path),
            "--output",
            str(tmp_path / "book.m4b"),
            "--no-config",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["skipped_chapters"] == [1]
    assert len(packed_files) == 1
    assert packed_files[0][1] == "Chapter 2"


def test_cli_convert_with_voice_speed_cover_then_pack(tmp_path, monkeypatch):
    manifest, manifest_path = make_book(tmp_path)
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
