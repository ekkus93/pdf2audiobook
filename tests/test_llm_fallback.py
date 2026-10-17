"""Provider failure is fail-closed unless deterministic fallback was explicitly enabled."""

import fitz
import pytest

from pdf2audiobook.config import LLM, Chapters, General, Pdf, Settings, load_settings
from pdf2audiobook.errors import LLMError
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.workspace import read_manifest


class FailingModel:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def complete_json(self, *, instructions, document_text):
        raise LLMError("Sanitized synthetic backend failure")


def fixture(tmp_path):
    source = tmp_path / "book.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((70, 70), "Chapter 1", fontsize=18)
    page.insert_text(
        (70, 115), "This deterministic prose survives optional model failure.", fontsize=11
    )
    doc.save(source)
    doc.close()
    return source


def settings(tmp_path, fallback):
    return Settings(
        general=General(output_dir=str(tmp_path / "out")),
        chapters=Chapters(allow_single_chapter=True),
        pdf=Pdf(ocr="never"),
        llm=LLM(enabled=True, structure=True, cleanup=True,
                classification=False, narration=False,
                fallback_to_deterministic=fallback),
    )


def test_default_model_failure_does_not_silently_fallback(tmp_path, monkeypatch):
    import pdf2audiobook.pipeline as pipeline

    monkeypatch.setattr(pipeline, "create_provider", lambda _: FailingModel())
    with pytest.raises(LLMError, match="Sanitized synthetic"):
        analyze_book(fixture(tmp_path), settings(tmp_path, fallback=False))


def test_explicit_fallback_discards_llm_and_retains_raw_transcript(tmp_path, monkeypatch):
    import json

    import pdf2audiobook.pipeline as pipeline

    monkeypatch.setattr(pipeline, "create_provider", lambda _: FailingModel())
    manifest_path = analyze_book(fixture(tmp_path), settings(tmp_path, fallback=True))
    manifest = read_manifest(manifest_path)
    assert manifest.chapters
    assert all(edit.provider != "llm" for edit in manifest.edits)
    assert any("explicit deterministic fallback" in warning for warning in manifest.warnings)
    transcript = (manifest_path.parent / "chapters" / "001.txt").read_text()
    assert "deterministic prose survives" in transcript
    audit = json.loads((manifest_path.parent / "reports" / "llm_cleanup_audit.json").read_text())
    assert audit["decisions"] == []


def test_fallback_can_only_be_enabled_by_explicit_settings():
    default, _ = load_settings(no_config=True, environ={})
    assert not default.llm.fallback_to_deterministic
    enabled, src = load_settings(
        no_config=True,
        environ={"PDF2AUDIOBOOK_LLM_FALLBACK_TO_DETERMINISTIC": "true"},
    )
    assert enabled.llm.fallback_to_deterministic
    assert src["llm.fallback_to_deterministic"].startswith("env:")
