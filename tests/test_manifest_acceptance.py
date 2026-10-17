"""Approved chapter manifest edits remain authoritative and invalidate only needed audio."""

import shutil

import fitz
import numpy as np
import pytest
from mutagen.mp3 import MP3

from pdf2audiobook.config import LLM, General, Pdf, Settings
from pdf2audiobook.pipeline import analyze_book, convert_book
from pdf2audiobook.workspace import digest_file, read_manifest, write_manifest


class FakeSpeech:
    sample_rate = 24000
    generations = 0

    def __init__(self, model):
        pass

    def generate(self, text, *, voice, speed):
        FakeSpeech.generations += 1
        return np.full(2400, 0.025, dtype=np.float32)


def fixture_book(tmp_path):
    source = tmp_path / "chapters.pdf"
    doc = fitz.open()
    for number in (1, 2):
        page = doc.new_page()
        page.insert_text((72, 72), f"Chapter {number}", fontsize=18)
        page.insert_text(
            (72, 120), f"Unique chapter number {number} has its own prose.", fontsize=11
        )
    doc.save(source)
    doc.close()
    settings = Settings(
        general=General(output_dir=str(tmp_path / "out")),
        pdf=Pdf(ocr="never"), llm=LLM(enabled=False),
    )
    return source, settings


def test_approved_mid_page_boundary_survives_reanalysis(tmp_path):
    source, settings = fixture_book(tmp_path)
    manifest_path = analyze_book(source, settings)
    manifest = read_manifest(manifest_path)
    assert len(manifest.chapters) == 2
    first, second = manifest.chapters
    original_start = second.start_block
    assert original_start + 1 < second.end_block
    first.end_block = original_start + 1
    second.start_block = original_start + 1
    first.manually_approved = second.manually_approved = True
    write_manifest(manifest_path, manifest)

    assert analyze_book(source, settings) == manifest_path
    actual = read_manifest(manifest_path)
    assert actual.chapters[0].end_block == original_start + 1
    assert actual.chapters[1].start_block == original_start + 1
    first_text = (manifest_path.parent / "chapters" / "001.txt").read_text()
    second_text = (manifest_path.parent / "chapters" / "002.txt").read_text()
    assert "Chapter 2" in first_text
    assert "Chapter 2" not in second_text
    assert "Unique chapter number 2" in second_text


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg unavailable")
def test_manual_title_and_selected_chapter_regenerate_only_selected_mp3(tmp_path, monkeypatch):
    import pdf2audiobook.pipeline as pipeline

    monkeypatch.setattr(pipeline, "KittenProvider", FakeSpeech)
    FakeSpeech.generations = 0
    source, settings = fixture_book(tmp_path)
    first, second = convert_book(source, settings)
    first_sha = digest_file(first)
    previous_generations = FakeSpeech.generations
    assert previous_generations > 0

    manifest_path = analyze_book(source, settings)
    manifest = read_manifest(manifest_path)
    manifest.chapters[1].title = "Approved Custom Chapter Title"
    manifest.chapters[1].manually_approved = True
    write_manifest(manifest_path, manifest)

    selected = convert_book(source, settings, chapter=2)
    assert len(selected) == 1
    assert "Approved Custom Chapter Title" in selected[0].name
    assert MP3(selected[0]).info.length > 0
    assert digest_file(first) == first_sha
    assert FakeSpeech.generations == previous_generations  # Valid WAV cache reused.
    assert read_manifest(manifest_path).chapters[1].manually_approved
