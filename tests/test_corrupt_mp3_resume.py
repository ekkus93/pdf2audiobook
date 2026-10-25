"""Corrupt MP3 cache entries must regenerate even when sidecar checksums match."""

import json

import numpy as np
import pytest

from pdf2audiobook import pipeline
from pdf2audiobook.audio import audio_output_path
from pdf2audiobook.config import Settings
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock
from pdf2audiobook.workspace import digest_bytes


@pytest.mark.parametrize(
    "sidecar_override",
    [
        None,
        "null",
        "[]",
        '"unexpected string"',
        "42",
        "{broken json",
        '{"padding":"' + "x" * 5000 + '"}',
        "[" * 100_000,
    ],
)
def test_resume_replaces_corrupt_mp3_even_with_matching_checksum(
    tmp_path,
    monkeypatch,
    sidecar_override,
):
    settings = Settings()
    settings.general.resume = True
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"synthetic placeholder")
    root = tmp_path / "book-output"
    manifest_path = root / "manifest.json"
    chapter = Chapter(
        id="chapter-1",
        number=1,
        title="Synthetic Chapter",
        start_block=0,
        end_block=1,
        confidence=1.0,
    )
    manifest = BookManifest(
        schema_version=3,
        input_sha256="synthetic-sha",
        title="Synthetic Book",
        source_path=str(source),
        blocks=[
            DocumentBlock(
                id="paragraph",
                text="Synthetic text.",
                span_ids=[],
                page_index=0,
            )
        ],
        chapters=[chapter],
    )
    chapter_dir = root / "chapters"
    chapter_dir.mkdir(parents=True)
    chapter_text = "Synthetic text."
    (chapter_dir / "001.txt").write_text(chapter_text, encoding="utf-8")
    output = audio_output_path(manifest, chapter, root)
    output.parent.mkdir(parents=True)
    invalid_mp3 = b"not an MPEG audio frame"
    output.write_bytes(invalid_mp3)
    record = output.with_suffix(".cache.json")
    valid_record = json.dumps(
        {
            "fingerprint": pipeline.chapter_audio_fingerprint(
                chapter_text,
                settings,
                manifest,
                chapter,
            ),
            "bytes": len(invalid_mp3),
            "sha256": digest_bytes(invalid_mp3),
        }
    )
    record.write_text(
        valid_record if sidecar_override is None else sidecar_override,
        encoding="utf-8",
    )

    class StubKitten:
        sample_rate = 24000

        def __init__(self, _model):
            pass

    regenerated = []
    monkeypatch.setattr(pipeline, "analyze_book", lambda *_, **_kw: manifest_path)
    monkeypatch.setattr(pipeline, "read_manifest", lambda *_: manifest)
    monkeypatch.setattr(pipeline, "render_chapter_texts", lambda *_: None)
    monkeypatch.setattr(pipeline, "KittenProvider", StubKitten)
    monkeypatch.setattr(
        pipeline,
        "synthesize_chunks",
        lambda *_args, **_kwargs: np.full(2400, 0.01, dtype=np.float32),
    )

    def publish(_audio, _rate, target, **_metadata):
        regenerated.append(target)
        target.write_bytes(b"new verified audio placeholder")
        return target

    monkeypatch.setattr(pipeline, "encode_mp3", publish)
    outputs = pipeline.convert_book(source, settings)
    assert outputs == [output]
    assert regenerated == [output]
    assert output.read_bytes() == b"new verified audio placeholder"
    latest = json.loads(record.read_text(encoding="utf-8"))
    assert latest["bytes"] == output.stat().st_size
    assert latest["sha256"] == digest_bytes(output.read_bytes())
