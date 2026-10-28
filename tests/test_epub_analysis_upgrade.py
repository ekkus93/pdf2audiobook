"""Workspaces analyzed by the old chapter detector are re-planned, not silently kept (E6)."""

import json
from pathlib import Path
from typing import Any

import pytest
from epub_book import write_novel_epub

from pdf2audiobook import pipeline
from pdf2audiobook.config import Settings
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.workspace import digest_file, fingerprint, read_manifest, write_manifest

MARKER = "STALE-PLAN-MARKER"


def _settings(tmp_path: Path) -> Settings:
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.llm.enabled = False
    settings.chapters.allow_single_chapter = True
    return settings


def _legacy_stages(book_hash: str, settings: Settings) -> dict[str, str]:
    """The stage fingerprints exactly as the detector computed them before this change."""
    return {
        "extraction": fingerprint("analysis-v22", book_hash, settings.pdf.model_dump()),
        "chapter-boundaries": fingerprint(
            settings.chapters.model_dump(
                exclude={"allow_single_chapter", "min_boundary_confidence"}
            )
        ),
        "llm-analysis": fingerprint("disabled"),
    }


def _analyze_as_before(source: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Path:
    book_hash = digest_file(source)
    with monkeypatch.context() as patch:
        patch.setattr(
            pipeline,
            "_analysis_stage_fingerprints",
            lambda _hash, current, _extractor: _legacy_stages(book_hash, current),
        )
        path = analyze_book(source, settings)
    manifest = read_manifest(path)
    manifest.warnings.append(MARKER)
    write_manifest(path, manifest)
    return path


def test_current_stage_fingerprints_differ_from_the_old_detector(tmp_path: Path) -> None:
    source = write_novel_epub(tmp_path / "n.epub", chapters=6)
    settings = _settings(tmp_path)
    current = pipeline._analysis_stage_fingerprints(digest_file(source), settings, None)
    legacy = _legacy_stages(digest_file(source), settings)
    assert current["extraction"] != legacy["extraction"]
    assert current["chapter-boundaries"] != legacy["chapter-boundaries"]
    assert current["llm-analysis"] == legacy["llm-analysis"]


def test_an_unapproved_workspace_is_replanned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = write_novel_epub(tmp_path / "n.epub", chapters=6)
    settings = _settings(tmp_path)
    path = _analyze_as_before(source, settings, monkeypatch)
    old = read_manifest(path)
    assert MARKER in old.warnings
    replanned = read_manifest(analyze_book(source, settings))
    assert MARKER not in replanned.warnings
    assert replanned.analysis_fingerprint != old.analysis_fingerprint


def test_a_workspace_with_an_approved_chapter_is_not_destroyed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = write_novel_epub(tmp_path / "n.epub", chapters=6)
    settings = _settings(tmp_path)
    path = _analyze_as_before(source, settings, monkeypatch)
    manifest = read_manifest(path)
    manifest.chapters[0].manually_approved = True
    write_manifest(path, manifest)
    before = path.read_bytes()
    with pytest.raises(ExtractionError, match="manually approved or protected"):
        analyze_book(source, settings)
    assert path.read_bytes() == before


class _CountingProvider:
    """Stands in for the model: every distinct request is a billable call."""

    def __init__(self) -> None:
        self.calls = 0
        self.last_usage: dict[str, int] = {}

    def __enter__(self) -> "_CountingProvider":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def complete_json(self, *, instructions: str, document_text: str) -> dict[str, Any]:
        self.calls += 1
        return {"headings": []}


def test_replanning_reuses_the_llm_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = write_novel_epub(tmp_path / "n.epub", chapters=6)
    settings = _settings(tmp_path)
    settings.llm.enabled = True
    settings.llm.cleanup = settings.llm.classification = settings.llm.narration = False
    settings.llm.structure = True
    provider = _CountingProvider()
    monkeypatch.setattr(pipeline, "create_provider", lambda _settings, **_kw: provider)
    book_hash = digest_file(source)
    real = pipeline._analysis_stage_fingerprints

    def as_before(_hash: str, current: Settings, extractor: Any) -> dict[str, str]:
        stages = real(_hash, current, extractor)
        return {
            **stages,
            **_legacy_stages(book_hash, current),
            "llm-analysis": stages["llm-analysis"],
        }

    with monkeypatch.context() as patch:
        patch.setattr(pipeline, "_analysis_stage_fingerprints", as_before)
        path = analyze_book(source, settings)
    first = provider.calls
    assert first > 0
    manifest = read_manifest(path)
    manifest.warnings.append(MARKER)
    write_manifest(path, manifest)
    replanned = analyze_book(source, settings)
    assert MARKER not in read_manifest(replanned).warnings  # it was re-planned ...
    assert provider.calls == first  # ... without asking the model anything again
    usage = json.loads((replanned.parent / "reports" / "llm_usage.json").read_text())
    assert usage["cache_hits"] == first and usage["cache_misses"] == 0
