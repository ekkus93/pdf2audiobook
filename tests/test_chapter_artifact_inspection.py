"""Chapter manifest, persisted text and inspect JSON constitute one auditable artifact set."""

import json
from pathlib import Path

import fitz
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.config import LLM, General, Pdf, Settings
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.workspace import read_manifest


def test_manifest_chapter_files_and_json_inspection_share_boundaries(tmp_path: Path):
    source = tmp_path / "inspectable.pdf"
    pdf = fitz.open()
    for number in (1, 2):
        page = pdf.new_page()
        page.insert_text((72, 100), f"Chapter {number}", fontsize=18)
        page.insert_text((72, 140), f"Evidence paragraph for chapter {number}.", fontsize=12)
    pdf.save(source)
    pdf.close()

    settings = Settings(
        general=General(output_dir=str(tmp_path / "output")),
        pdf=Pdf(ocr="never"),
        llm=LLM(enabled=False),
    )
    path = analyze_book(source, settings)
    manifest = read_manifest(path)
    assert path.name == "manifest.json"
    assert len(manifest.chapters) == 2
    assert manifest.chapters[0].end_block == manifest.chapters[1].start_block
    for chapter in manifest.chapters:
        rendered = path.parent / "chapters" / f"{chapter.number:03d}.txt"
        assert rendered.is_file()
        assert f"Evidence paragraph for chapter {chapter.number}." in rendered.read_text()

    inspected = CliRunner().invoke(app, ["inspect", str(path), "--json"])
    assert inspected.exit_code == 0, inspected.output
    payload = json.loads(inspected.stdout)
    assert len(payload["chapters"]) == 2
    assert payload["chapters"] == [c.model_dump() for c in manifest.chapters]
    assert payload["coverage"]["source_blocks"] == len(manifest.blocks)
    assert payload["coverage"]["uncovered_blocks"] == 0
    assert payload["coverage"]["valid"] is True
    assert payload["warnings"] == manifest.warnings
    assert (path.parent / "coverage.json").is_file()
