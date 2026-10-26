"""Resume must verify ID3 chapter identity even with a matching sidecar checksum."""

import hashlib
import json
import shutil

import numpy as np
import pytest
from mutagen.easyid3 import EasyID3

from pdf2audiobook import pipeline
from pdf2audiobook.audio import audio_output_path
from pdf2audiobook.config import Settings
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock
from pdf2audiobook.workspace import digest_file


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
@pytest.mark.parametrize(
    ("altered_tag", "bad_value"),
    [
        (None, None),
        ("title", "Wrong chapter"),
        ("album", "Wrong book"),
        ("tracknumber", "17"),
        ("artist", "Wrong author"),
        ("remove_title", None),
    ],
)
def test_mp3_resume_checks_actual_chapter_id3_tags(
    tmp_path,
    monkeypatch,
    altered_tag,
    bad_value,
):
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"synthetic placeholder")
    root = tmp_path / "output"
    manifest_path = root / "manifest.json"
    settings = Settings()
    settings.general.resume = True
    chapter = Chapter(
        id="chapter-1",
        number=1,
        title="Chapter One",
        start_block=0,
        end_block=1,
        confidence=1.0,
    )
    manifest = BookManifest(
        schema_version=3,
        input_sha256="synthetic-sha",
        title="Example Book",
        author="Example Author",
        source_path=str(source),
        blocks=[
            DocumentBlock(
                id="body",
                text="A synthetic sentence.",
                page_index=0,
            )
        ],
        chapters=[chapter],
    )
    chapter_text = "A synthetic sentence."
    chapters_dir = root / "chapters"
    chapters_dir.mkdir(parents=True)
    (chapters_dir / "001.txt").write_text(chapter_text, encoding="utf-8")
    output = audio_output_path(manifest, chapter, root)
    original_encode = pipeline.encode_mp3
    audio = np.full(2400, 0.01, dtype=np.float32)
    original_encode(
        audio,
        24000,
        output,
        bitrate=settings.tts.bitrate,
        target_rate=settings.tts.sample_rate,
        title=chapter.title,
        artist=manifest.author,
        album=manifest.title,
        track=chapter.number,
    )
    if altered_tag:
        tags = EasyID3(output)
        if altered_tag == "remove_title":
            del tags["title"]
        else:
            tags[altered_tag] = bad_value
        tags.save()

    sidecar = output.with_suffix(".cache.json")
    sidecar.write_text(
        json.dumps(
            {
                "chapter_id": chapter.id,
                "sidecar_version": 3,
                "rendering_inputs": {"footnotes": settings.pdf.footnotes},
                "text_sha256": hashlib.sha256(chapter_text.encode("utf-8")).hexdigest(),
                "fingerprint": pipeline.chapter_audio_fingerprint(
                    chapter_text,
                    settings,
                    manifest,
                    chapter,
                ),
                "bytes": output.stat().st_size,
                "sha256": digest_file(output),
            }
        ),
        encoding="utf-8",
    )

    class StubKitten:
        sample_rate = 24000

        def __init__(self, _model):
            pass

    generated = []
    monkeypatch.setattr(pipeline, "analyze_book", lambda *_, **_kw: manifest_path)
    monkeypatch.setattr(pipeline, "read_manifest", lambda *_: manifest)
    monkeypatch.setattr(pipeline, "render_chapter_texts", lambda *_: None)
    monkeypatch.setattr(pipeline, "KittenProvider", StubKitten)
    monkeypatch.setattr(
        pipeline,
        "synthesize_chunks",
        lambda *_args, **_kwargs: audio,
    )

    def spy_encode(*args, **kwargs):
        generated.append(True)
        return original_encode(*args, **kwargs)

    monkeypatch.setattr(pipeline, "encode_mp3", spy_encode)
    assert pipeline.convert_book(source, settings) == [output]
    assert len(generated) == (0 if altered_tag is None else 1)
    tags = EasyID3(output)
    assert tags["title"] == [chapter.title]
    assert tags["album"] == [manifest.title]
    assert tags["tracknumber"] == [str(chapter.number)]
    assert tags["artist"] == [manifest.author]
    assert json.loads(sidecar.read_text(encoding="utf-8"))["sha256"] == digest_file(output)
