"""A name patched on `pipeline` reaches the analysis code (module split MS4.03).

Each test wraps a `pipeline` name with a recorder, runs `analyze_book`, and
asserts that code in `pdf2audiobook.analysis` called the patched object. If
`pipeline._analysis_services()` passed the original instead, the recorder
would never see a call from analysis.
"""

import sys
from types import SimpleNamespace

import fitz
import pytest

from pdf2audiobook import pipeline
from pdf2audiobook.config import LLM, General, Settings
from pdf2audiobook.models import Chapter, DocumentBlock

ANALYSIS = "pdf2audiobook.analysis"


def _record_callers(monkeypatch, name, replacement=None):
    """Patch `pipeline.<name>` with a wrapper that records the calling module."""
    target = replacement if replacement is not None else getattr(pipeline, name)
    callers: list[str] = []

    def recorder(*args, **kwargs):
        callers.append(sys._getframe(1).f_globals.get("__name__", ""))
        return target(*args, **kwargs)

    monkeypatch.setattr(pipeline, name, recorder)
    return callers


def _book(tmp_path):
    source = tmp_path / "book.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 80), "Chapter 1")
    page.insert_text((72, 120), "The first chapter has enough readable prose.")
    page.insert_text((72, 180), "Chapter 2")
    page.insert_text((72, 220), "The second chapter has more readable prose.")
    document.save(source)
    document.close()
    settings = Settings(general=General(output_dir=str(tmp_path / "out")), llm=LLM(enabled=False))
    return source, settings


@pytest.mark.parametrize("name", ["digest_file", "render_chapter_texts", "write_json"])
def test_patched_name_is_called_by_analysis(tmp_path, monkeypatch, name):
    source, settings = _book(tmp_path)
    callers = _record_callers(monkeypatch, name)

    pipeline.analyze_book(source, settings)

    assert ANALYSIS in callers


def test_patched_read_manifest_is_called_when_analysis_is_reused(tmp_path, monkeypatch):
    source, settings = _book(tmp_path)
    pipeline.analyze_book(source, settings)
    callers = _record_callers(monkeypatch, "read_manifest")

    pipeline.analyze_book(source, settings)

    assert ANALYSIS in callers


class _Provider:
    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        return False


def test_patched_cached_llm_provider_wraps_the_analysis_provider(tmp_path, monkeypatch):
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"synthetic placeholder")
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.llm.structure = True
    settings.llm.cleanup = False
    settings.llm.classification = False
    settings.llm.narration = False
    block = DocumentBlock(id="b1", span_ids=[], text="Synthetic text.", page_index=0, order=0)
    extracted = SimpleNamespace(
        blocks=[block],
        spans=[],
        toc=[],
        page_sizes=[(612.0, 792.0)],
        title="Synthetic",
        author=None,
        warnings=[],
    )
    chapter = Chapter(
        id="c1", number=1, title="Synthetic", start_block=0, end_block=1, confidence=1.0
    )
    monkeypatch.setattr(pipeline, "extract_pdf", lambda *a, **k: extracted)
    monkeypatch.setattr(pipeline, "pagination_cleanup", lambda *a, **k: [])
    monkeypatch.setattr(pipeline, "create_provider", lambda *a, **k: _Provider())
    monkeypatch.setattr(pipeline, "detect_llm_headings", lambda *a, **k: (set(), []))
    monkeypatch.setattr(pipeline, "propose_chapters", lambda *a, **k: ([chapter], []))
    monkeypatch.setattr(pipeline, "render_chapter_texts", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "write_json", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "write_manifest", lambda *a, **k: None)
    callers = _record_callers(
        monkeypatch, "CachedLLMProvider", replacement=lambda provider, **_kw: provider
    )

    pipeline.analyze_book(source, settings)

    assert ANALYSIS in callers
