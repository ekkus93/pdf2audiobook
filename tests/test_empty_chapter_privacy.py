"""Chapters with no narration are reported and gated without leaking source data."""

import fitz
import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.config import LLM, General, Pdf, Settings
from pdf2audiobook.errors import AudioError
from pdf2audiobook.models import DocumentBlock, SourceSpan
from pdf2audiobook.pdf import ExtractedDocument
from pdf2audiobook.pipeline import analyze_book, convert_book
from pdf2audiobook.workspace import read_manifest

runner = CliRunner()


class FootnoteOnlyExtractor:
    name = "footnote-only-test"

    def extract(self, _source, _settings, *, ocr_cache_dir=None, source_sha256=None):
        span = SourceSpan(id="s1", page_index=0, text="PRIVATE_OMITTED_NOTE")
        block = DocumentBlock(
            id="b1",
            span_ids=["s1"],
            text="PRIVATE_OMITTED_NOTE",
            page_index=0,
            kind="footnote",
        )
        return ExtractedDocument(
            title="PRIVATE_BOOK_TITLE",
            author=None,
            toc=[],
            spans=[span],
            blocks=[block],
            warnings=[],
            page_sizes=[(600, 800)],
        )


def test_analyze_reports_empty_chapter_and_convert_refuses_privately(tmp_path):
    source = tmp_path / "PRIVATE_BOOK_PATH.pdf"
    with fitz.open() as document:
        document.new_page()
        document.save(source)
    settings = Settings(
        general=General(output_dir=str(tmp_path / "output")),
        pdf=Pdf(footnotes="omit"),
        llm=LLM(enabled=False),
        chapters={"allow_single_chapter": True},
    )
    extractor = FootnoteOnlyExtractor()
    manifest_path = analyze_book(source, settings, extractor=extractor)
    manifest = read_manifest(manifest_path)
    assert "No speakable text after accepted cleanup; review manually" in (
        manifest.chapters[0].warnings
    )
    assert "Chapter 1 has no speakable text" in " ".join(manifest.warnings)
    import json

    coverage = json.loads((manifest_path.parent / "coverage.json").read_text())
    assert coverage["empty_chapters"] == [1]

    with pytest.raises(AudioError) as raised:
        convert_book(source, settings, extractor=extractor)
    message = str(raised.value)
    assert "Chapter 1" in message
    assert "PRIVATE_BOOK_PATH" not in message
    assert "PRIVATE_BOOK_TITLE" not in message
    assert "PRIVATE_OMITTED_NOTE" not in message
    assert str(tmp_path) not in message


def test_approved_empty_chapter_is_skipped_without_partial_failure(tmp_path):
    import json

    from pdf2audiobook.workspace import write_manifest

    source = tmp_path / "approved-empty.pdf"
    with fitz.open() as document:
        document.new_page()
        document.save(source)
    settings = Settings(
        general=General(output_dir=str(tmp_path / "output")),
        pdf=Pdf(footnotes="omit"),
        llm=LLM(enabled=False),
        chapters={"allow_single_chapter": True},
    )
    extractor = FootnoteOnlyExtractor()
    manifest_path = analyze_book(source, settings, extractor=extractor)
    manifest = read_manifest(manifest_path)
    manifest.chapters[0].manually_approved = True
    write_manifest(manifest_path, manifest)
    assert convert_book(source, settings, extractor=extractor) == []
    status = json.loads((manifest_path.parent / "reports" / "conversion_status.json").read_text())
    assert status["chapters"][0]["status"] == "skipped"
    assert status["chapters"][0]["reason_code"] == "empty_chapter"


def test_empty_chapter_acceptance_error_does_not_echo_private_path(tmp_path):
    source = tmp_path / "PRIVATE_BOOK_PATH.pdf"
    source.write_bytes(b"synthetic")
    result = runner.invoke(
        app,
        ["convert", str(source), "--no-config", "--accept-review", "empty_chapter"],
    )
    assert result.exit_code == 2
    assert "PRIVATE_BOOK_PATH" not in result.stderr
    assert str(tmp_path) not in result.stderr
