"""Explicit opt-in real local model smoke; recordings and generated audio stay outside Git."""

from __future__ import annotations

import os
from pathlib import Path

import fitz
import pytest
from mutagen.mp3 import MP3

REFERENCE = os.environ.get("PDF2AUDIOBOOK_TEST_CLONE_REFERENCE")
pytestmark = pytest.mark.skipif(
    not REFERENCE, reason="set PDF2AUDIOBOOK_TEST_CLONE_REFERENCE for real-model acceptance"
)


def test_real_local_clone_and_warm_resume(tmp_path, monkeypatch):
    from pdf2audiobook.config import Settings
    from pdf2audiobook.pipeline import convert_book
    from pdf2audiobook.tts.catalog import require_model

    require_model()  # Missing prerequisites fail when explicitly enabled; never download here.
    output = Path(os.environ.get("PDF2AUDIOBOOK_TEST_CLONE_OUTPUT", str(tmp_path / "audio")))
    source = tmp_path / "acceptance.pdf"
    with fitz.open() as document:
        for n in (1, 2):
            page = document.new_page()
            page.insert_text((80, 60), f"Chapter {n}")
            page.insert_text(
                (80, 115),
                "The lighthouse keeper opened the door. A small light shone across the quiet sea.",
            )
        document.save(source)
    settings = Settings()
    settings.general.output_dir = str(output)
    settings.llm.enabled = False
    settings.pdf.ocr = "never"
    settings.tts.kitten.model = "kitten2"
    settings.tts.voice_clone.enabled = True
    settings.tts.voice_clone.reference_audio = REFERENCE
    settings.tts.voice_clone.reference_text_file = os.environ.get(
        "PDF2AUDIOBOOK_TEST_CLONE_TRANSCRIPT"
    )
    files = convert_book(source, settings)
    assert len(files) == 2 and all(MP3(path).info.length > 0.1 for path in files)
    before = {path: path.stat().st_mtime_ns for path in files}
    monkeypatch.setattr(
        "pdf2audiobook.tts.clone_provider.KittenCloneProvider",
        lambda *_: pytest.fail("warm resume loaded a model"),
    )
    assert convert_book(source, settings) == files
    assert {path: path.stat().st_mtime_ns for path in files} == before


@pytest.mark.skipif(
    os.environ.get("PDF2AUDIOBOOK_TEST_CLONE_LONG_FORM") != "1",
    reason="set PDF2AUDIOBOOK_TEST_CLONE_LONG_FORM=1 for the longer chunk-continuity sample",
)
def test_real_local_clone_multiple_chunks(tmp_path):
    from pdf2audiobook.audio.progress import read_synthesis_progress
    from pdf2audiobook.config import Settings
    from pdf2audiobook.pipeline import convert_book
    from pdf2audiobook.tts.catalog import require_model

    require_model()
    output = Path(os.environ.get("PDF2AUDIOBOOK_TEST_CLONE_OUTPUT", str(tmp_path / "audio")))
    source = tmp_path / "continuity.pdf"
    paragraphs = [
        "The keeper climbed the narrow stairs with a lantern in her hand. Outside, the wind "
        "moved across the harbor and the fishing boats rocked against their ropes. She paused "
        "at the window to watch the last small boat return before the storm.",
        "At the top of the tower she opened the brass cover and checked the lamp. Its steady "
        "flame cast a warm circle on the floor. Far below, a child waved from the village road. "
        "The keeper lifted her lantern in answer, then turned back to her work.",
        "Rain began to strike the glass as the great lens slowly turned. The light swept over "
        "the water, across the rocks, and out toward the distant ships. The keeper listened to "
        "the quiet rhythm of the mechanism and wrote the time in her notebook.",
        "By morning the clouds had moved beyond the headland. The harbor was calm again, and "
        "every boat had returned safely. She closed the notebook, extinguished the small "
        "lantern, and walked down the stairs to share breakfast with the village.",
    ]
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((80, 60), "Chapter 1")
        assert page.insert_textbox((80, 115, 530, 700), "\n\n".join(paragraphs)) > 0
        document.save(source)
    settings = Settings()
    settings.general.output_dir = str(output / "continuity")
    settings.llm.enabled = False
    settings.pdf.ocr = "never"
    settings.tts.kitten.model = "kitten2"
    settings.tts.voice_clone.enabled = True
    settings.tts.voice_clone.reference_audio = REFERENCE
    settings.tts.voice_clone.reference_text_file = os.environ.get(
        "PDF2AUDIOBOOK_TEST_CLONE_TRANSCRIPT"
    )
    files = convert_book(source, settings)
    assert len(files) == 1 and MP3(files[0]).info.length > 30
    ledgers = list((files[0].parent.parent / ".cache/tts/progress").glob("*.json"))
    assert len(ledgers) == 1
    progress = read_synthesis_progress(ledgers[0])
    assert progress is not None and progress["total_chunks"] >= 3
    assert progress["completed_chunks"] == progress["total_chunks"]
    assert progress["status"] == "completed"
