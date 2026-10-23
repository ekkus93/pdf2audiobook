from pathlib import Path

import fitz

from pdf2audiobook.config import Settings
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.workspace import read_manifest


def test_llm_assists_with_nonstandard_chapter_heading(monkeypatch, tmp_path: Path):
    source = tmp_path / "unusual.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((80, 80), "Opening Scene")
    page.insert_text((80, 130), "This is the beginning of the story.")
    document.save(source)
    document.close()

    class MockProvider:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def complete_json(self, **kwargs):
            return {
                "headings": [
                    {"block_id": "p00001-l00001", "title": "Opening Scene", "confidence": 0.99}
                ]
            }

    monkeypatch.setattr("pdf2audiobook.pipeline.create_provider", lambda settings: MockProvider())
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.pdf.ocr = "never"
    manifest = read_manifest(analyze_book(source, settings))
    assert [c.title for c in manifest.chapters] == ["Opening Scene"]
    assert manifest.analysis_fingerprint is not None
