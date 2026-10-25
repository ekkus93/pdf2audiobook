"""Offline mixed embedded/scanned PDF acceptance with stubbed region OCR."""

import shutil

import fitz
import numpy as np
import pytest
from mutagen.mp3 import MP3

from pdf2audiobook.config import LLM, General, Pdf, Settings
from pdf2audiobook.pipeline import analyze_book, convert_book
from pdf2audiobook.workspace import read_manifest


def test_auto_ocr_skips_image_free_blank_and_short_valid_text_without_tesseract(
    tmp_path, monkeypatch
):
    import pdf2audiobook.pdf as pdf

    source = tmp_path / "born-digital.pdf"
    document = fitz.open()
    document.new_page(width=600, height=800)  # Deliberately blank.
    page = document.new_page(width=600, height=800)
    page.insert_text((70, 100), "Part One", fontsize=18)
    document.save(source)
    document.close()

    monkeypatch.setattr(pdf.shutil, "which", lambda name: None if name == "tesseract" else "/bin")

    def fail_if_called(_page, _settings):
        raise AssertionError("auto OCR should not run on image-free pages")

    monkeypatch.setattr(pdf, "_ocr_page_lines", fail_if_called)
    manifest_path = analyze_book(
        source,
        Settings(
            general=General(output_dir=str(tmp_path / "out")),
            pdf=Pdf(ocr="auto"),
            llm=LLM(enabled=False),
        ),
    )
    manifest = read_manifest(manifest_path)
    assert manifest.blocks
    assert all(block.page_index == 1 for block in manifest.blocks)
    assert all(span.origin == "embedded" for span in manifest.spans)
    assert any("Page 1: no readable text" in warning for warning in manifest.warnings)


class FakeVoice:
    sample_rate = 24000

    def __init__(self, model):
        pass

    def generate(self, text, *, voice, speed):
        return np.full(2400, 0.02, dtype=np.float32)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg unavailable")
def test_auto_ocr_mixed_pdf_without_duplicates_and_with_clean_folios(tmp_path, monkeypatch):
    import pdf2audiobook.pdf as pdf
    import pdf2audiobook.pipeline as pipeline

    source = tmp_path / "mixed.pdf"
    doc = fitz.open()
    page1 = doc.new_page(width=600, height=800)
    page1.insert_text((70, 70), "Chapter 1", fontsize=18)
    page1.insert_text(
        (70, 120), "Embedded first chapter has adequate selectable text.", fontsize=11
    )
    page1.insert_text((296, 780), "1", fontsize=10)

    # Make page 2 an actual embedded raster image, with no selectable text.
    raster = fitz.open()
    scan = raster.new_page(width=600, height=800)
    scan.insert_text((70, 70), "Chapter 2", fontsize=18)
    scan.insert_text((70, 120), "Scanned second chapter recovered via OCR.", fontsize=11)
    scan.insert_text((296, 780), "2", fontsize=10)
    image = scan.get_pixmap().tobytes("png")
    raster.close()
    page2 = doc.new_page(width=600, height=800)
    page2.insert_image(page2.rect, stream=image)
    doc.save(source)
    doc.close()

    calls = []

    def offline_ocr(page, settings):
        calls.append(page.number)
        assert page.number == 1  # Page 1 has sufficient embedded text.
        return [
            {"text": "Chapter 2", "bbox": (70, 52, 170, 76), "font": "FakeOCR", "size": 18},
            {
                "text": "Scanned second chapter recovered via OCR.",
                "bbox": (70, 108, 410, 123),
                "font": "FakeOCR",
                "size": 11,
            },
            {"text": "2", "bbox": (294, 766, 304, 781), "font": "FakeOCR", "size": 10},
        ]

    monkeypatch.setattr(pdf, "_ocr_page_lines", offline_ocr)
    monkeypatch.setattr(pipeline, "KittenProvider", FakeVoice)
    settings = Settings(
        general=General(output_dir=str(tmp_path / "output")),
        pdf=Pdf(ocr="auto"),
        llm=LLM(enabled=False),
    )
    outputs = convert_book(source, settings)
    assert len(outputs) == 2
    assert all(path.is_file() and MP3(path).info.length > 0 for path in outputs)
    assert calls == [1]
    manifest_path = next((tmp_path / "output").glob("*/manifest.json"))
    manifest = read_manifest(manifest_path)
    assert {span.origin for span in manifest.spans if span.page_index == 0} == {"embedded"}
    assert {span.origin for span in manifest.spans if span.page_index == 1} == {"ocr"}
    combined = " ".join(
        (manifest_path.parent / "chapters" / f"{number:03d}.txt").read_text() for number in (1, 2)
    )
    assert combined.count("Embedded first chapter") == 1
    assert combined.count("Scanned second chapter") == 1
    assert "\n1\n" not in combined and "\n2\n" not in combined
    assert any(edit.accepted and edit.original == "1" for edit in manifest.edits)
    assert any(edit.accepted and edit.original == "2" for edit in manifest.edits)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg unavailable")
def test_image_only_scanned_book_uses_ocr_auto(tmp_path, monkeypatch):
    import pdf2audiobook.pdf as pdf
    import pdf2audiobook.pipeline as pipeline

    source = tmp_path / "scan.pdf"
    raster = fitz.open()
    target = raster.new_page(width=600, height=800)
    target.insert_text((70, 70), "Chapter 1", fontsize=18)
    target.insert_text((70, 120), "Image only book narration from OCR.", fontsize=11)
    image = target.get_pixmap().tobytes("png")
    raster.close()
    book = fitz.open()
    page = book.new_page(width=600, height=800)
    page.insert_image(page.rect, stream=image)
    book.save(source)
    book.close()

    calls = []

    def stub_ocr(page, settings):
        calls.append(page.number)
        return [
            {"text": "Chapter 1", "bbox": (70, 52, 170, 76), "font": "OCR", "size": 18},
            {
                "text": "Image only book narration from OCR.",
                "bbox": (70, 108, 410, 123),
                "font": "OCR",
                "size": 11,
            },
        ]

    monkeypatch.setattr(pdf, "_ocr_page_lines", stub_ocr)
    monkeypatch.setattr(pipeline, "KittenProvider", FakeVoice)
    settings = Settings(
        general=General(output_dir=str(tmp_path / "out")),
        pdf=Pdf(ocr="auto"),
        llm=LLM(enabled=False),
    )
    outputs = convert_book(source, settings)
    assert len(outputs) == 1
    assert outputs[0].exists() and MP3(outputs[0]).info.length > 0
    assert calls == [0]
    manifest_path = next((tmp_path / "out").glob("*/manifest.json"))
    manifest = read_manifest(manifest_path)
    assert manifest.spans and all(span.origin == "ocr" for span in manifest.spans)
    transcript = (manifest_path.parent / "chapters" / "001.txt").read_text()
    assert transcript.count("Image only book narration from OCR.") == 1
