from pathlib import Path

import fitz
import numpy as np
import pytest
from mutagen.easyid3 import EasyID3

from pdf2audiobook.config import Settings
from pdf2audiobook.pipeline import convert_book


@pytest.mark.usefixtures("monkeypatch")
def test_convert_and_resume_with_fake_kitten(monkeypatch, tmp_path: Path):
    import shutil

    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg not installed")

    source = tmp_path / "chapters.pdf"
    pdf = fitz.open()
    for index in range(2):
        page = pdf.new_page()
        page.insert_text((80, 60), f"Chapter {index + 1}")
        page.insert_text((80, 115), f"Test sentence from chapter {index + 1}.")
    pdf.save(source)
    pdf.close()

    calls = []

    class FakeKitten:
        sample_rate = 24000

        def __init__(self, model):
            self.model = model

        def generate(self, text, *, voice, speed):
            calls.append((text, voice, speed))
            return np.ones(2400, dtype=np.float32) * 0.03

    monkeypatch.setattr("pdf2audiobook.pipeline.KittenProvider", FakeKitten)
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.pdf.ocr = "never"
    settings.llm.enabled = False
    files = convert_book(source, settings)
    assert len(files) == 2
    assert all(path.stat().st_size > 0 for path in files)
    assert EasyID3(files[0])["tracknumber"] == ["1"]
    calls_made = len(calls)
    assert calls_made >= 2
    assert convert_book(source, settings) == files
    assert len(calls) == calls_made
    settings.tts.kitten.voice = "Bella"
    convert_book(source, settings)
    assert len(calls) > calls_made
