"""Unapproved edits detected by the generated fingerprint survive reanalysis."""

import fitz

import pdf2audiobook.pipeline as pipeline
from pdf2audiobook.config import LLM, General, Settings
from pdf2audiobook.models import generated_chapter_fingerprint
from pdf2audiobook.workspace import read_manifest, write_manifest


def _source(path):
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 80), "Chapter 1")
    page.insert_text((72, 120), "First chapter contains enough readable prose.")
    page.insert_text((72, 180), "Chapter 2")
    page.insert_text((72, 220), "Second chapter contains more readable prose.")
    document.save(path)
    document.close()


def test_user_edited_chapter_survives_reanalysis_while_others_recompute(tmp_path, monkeypatch):
    source = tmp_path / "book.pdf"
    _source(source)
    settings = Settings(
        general=General(output_dir=str(tmp_path / "out")),
        llm=LLM(enabled=False),
    )
    manifest_path = pipeline.analyze_book(source, settings)
    manifest = read_manifest(manifest_path)
    assert len(manifest.chapters) == 2

    manifest.chapters[0].title = "My private edited title"
    assert manifest.chapters[0].generated_fingerprint != generated_chapter_fingerprint(
        manifest.chapters[0]
    )
    write_manifest(manifest_path, manifest)

    original_propose = pipeline.propose_chapters

    def changed_proposal(*args, **kwargs):
        chapters, warnings = original_propose(*args, **kwargs)
        chapters[1].title = "Recomputed second title"
        return chapters, warnings

    monkeypatch.setattr(pipeline, "propose_chapters", changed_proposal)
    settings.chapters.min_boundary_confidence = 0.8
    settings.general.resume = False
    refreshed = read_manifest(pipeline.analyze_book(source, settings))
    assert refreshed.chapters[0].title == "My private edited title"
    assert refreshed.chapters[1].title == "Recomputed second title"
    assert not refreshed.chapters[0].manually_approved
    assert "Preserved user-edited chapter numbers: 1" in refreshed.warnings
    assert "My private edited title" not in " ".join(refreshed.warnings)
