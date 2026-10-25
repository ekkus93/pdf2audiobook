"""Analysis fingerprints and deterministic cleanup decisions survive safe reuse (R82, R87)."""

import fitz
from typer.testing import CliRunner

import pdf2audiobook.pipeline as pipeline
from pdf2audiobook.cli import app
from pdf2audiobook.config import LLM, General, Settings
from pdf2audiobook.workspace import read_manifest, write_manifest


def _book(path, *, pages=1):
    document = fitz.open()
    for index in range(pages):
        page = document.new_page(width=600, height=800)
        page.insert_text((80, 80), f"Chapter {index + 1}")
        page.insert_text((80, 130), f"Chapter {index + 1} has enough prose for analysis.")
        if pages > 1:
            page.insert_text((295, 780), str(index + 1), fontsize=9)
    document.save(path)
    document.close()


def _settings(tmp_path, *, resume=True):
    return Settings(
        general=General(output_dir=str(tmp_path / "output"), resume=resume),
        llm=LLM(enabled=False),
    )


def test_approved_analysis_accepts_min_boundary_confidence_change(tmp_path):
    source = tmp_path / "book.pdf"
    _book(source)
    settings = _settings(tmp_path)
    manifest_path = pipeline.analyze_book(source, settings)
    manifest = read_manifest(manifest_path)
    manifest.approved = True
    write_manifest(manifest_path, manifest)

    changed = settings.model_copy(deep=True)
    changed.general.resume = False
    changed.chapters.min_boundary_confidence = 0.99
    assert pipeline.analyze_book(source, changed) == manifest_path


def test_disabled_llm_model_change_does_not_invalidate_approved_analysis(tmp_path):
    source = tmp_path / "book.pdf"
    _book(source)
    settings = _settings(tmp_path)
    manifest_path = pipeline.analyze_book(source, settings)
    manifest = read_manifest(manifest_path)
    manifest.approved = True
    write_manifest(manifest_path, manifest)

    changed = settings.model_copy(deep=True)
    changed.llm.ollama.model = "unused-model-change"
    assert pipeline.analyze_book(source, changed) == manifest_path


def test_no_resume_dry_run_keeps_approved_analysis_when_stages_match(tmp_path):
    source = tmp_path / "book.pdf"
    _book(source)
    settings = _settings(tmp_path)
    manifest_path = pipeline.analyze_book(source, settings)
    manifest = read_manifest(manifest_path)
    manifest.approved = True
    write_manifest(manifest_path, manifest)

    result = CliRunner().invoke(
        app,
        [
            "convert",
            str(source),
            "--no-config",
            "--no-llm",
            "--ocr",
            "auto",
            "--output",
            str(tmp_path / "output"),
            "--no-resume",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stderr


def test_rejected_page_number_removal_survives_reanalysis(tmp_path):
    source = tmp_path / "numbered.pdf"
    _book(source, pages=3)
    settings = _settings(tmp_path)
    settings.pdf.ocr = "never"
    manifest_path = pipeline.analyze_book(source, settings)
    manifest = read_manifest(manifest_path)
    page_number = next(edit for edit in manifest.edits if edit.original == "1")
    assert page_number.accepted
    block_id = page_number.block_id
    page_number.accepted = False
    write_manifest(manifest_path, manifest)

    changed = settings.model_copy(deep=True)
    changed.pdf.ocr = "auto"
    changed.general.resume = False
    refreshed = read_manifest(pipeline.analyze_book(source, changed))
    preserved = next(edit for edit in refreshed.edits if edit.block_id == block_id)
    assert preserved.accepted is False
    assert any(block.id == block_id and block.text == "1" for block in refreshed.blocks)
