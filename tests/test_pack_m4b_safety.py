"""M4B packaging verifies current audio and conversion removes only owned files."""

import json
import shutil

import numpy as np
import pytest
from typer.testing import CliRunner

from pdf2audiobook.audio import audio_output_path, encode_mp3
from pdf2audiobook.cli import app
from pdf2audiobook.config import Settings
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
        schema_version=2,
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


def test_pack_m4b_cli_refuses_stale_audio_without_disclosing_content(tmp_path):
    settings = Settings()
    manifest, chapter, manifest_path = make_book(tmp_path)
    output = audio_output_path(manifest, chapter, tmp_path)
    add_sidecar(output, manifest, chapter, settings, fingerprint="stale-identity")

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
