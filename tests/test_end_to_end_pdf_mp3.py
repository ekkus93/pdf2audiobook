"""Offline end-to-end extraction, chapter audio and cached rerun acceptance."""

import shutil

import fitz
import numpy as np
import pytest
from mutagen.mp3 import MP3

from pdf2audiobook.config import LLM, General, Pdf, Settings
from pdf2audiobook.pipeline import convert_book

class FakeKitten:
    sample_rate = 24000
    initialized = 0
    generated = 0

    def __init__(self, model):
        FakeKitten.initialized += 1

    def generate(self, text, *, voice, speed):
        FakeKitten.generated += 1
        return np.full(2400, 0.025, dtype=np.float32)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg unavailable")
def test_two_chapter_pdf_to_mp3_and_repeat_cache(tmp_path, monkeypatch):
    import pdf2audiobook.pipeline as pipeline

    monkeypatch.setattr(pipeline, "KittenProvider", FakeKitten)
    FakeKitten.initialized = 0
    FakeKitten.generated = 0
    source = tmp_path / "book.pdf"
    doc = fitz.open()
    for number in (1, 2):
        page = doc.new_page()
        page.insert_text((70, 70), f"Chapter {number}", fontsize=20)
        page.insert_text(
            (70, 110),
            f"This is a complete synthetic chapter number {number}. "
            "The spoken content is owned by the test suite.",
            fontsize=11,
        )
    doc.save(source)
    doc.close()

    settings = Settings(
        general=General(output_dir=str(tmp_path / "outputs")),
        pdf=Pdf(ocr="never"),
        llm=LLM(enabled=False),
    )
    files = convert_book(source, settings)
    assert len(files) == 2
    assert all(path.exists() and MP3(path).info.length > 0 for path in files)
    assert files[0].name.startswith("001")
    assert files[1].name.startswith("002")
    first_count = FakeKitten.generated
    assert first_count >= 2
    assert FakeKitten.initialized == 1
    assert list((files[0].parent.parent / ".cache" / "tts" / "progress").glob("*.json"))

    repeat = convert_book(source, settings)
    assert repeat == files
    assert FakeKitten.generated == first_count
    assert FakeKitten.initialized == 1  # Valid final MP3s bypass model loading.

    # One broken MP3 must be re-encoded without regenerating valid WAV chunks.
    files[0].write_bytes(b"invalid")
    repaired = convert_book(source, settings)
    assert repaired == files
    assert MP3(repaired[0]).info.length > 0
    assert FakeKitten.generated == first_count
