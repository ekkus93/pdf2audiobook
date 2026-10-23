"""LLM structure warnings must not erase deterministic footnote audit warnings."""

from types import SimpleNamespace

import pytest

from pdf2audiobook import pipeline
from pdf2audiobook.config import Settings
from pdf2audiobook.errors import LLMError
from pdf2audiobook.models import Chapter, DocumentBlock


class _Provider:
    def __enter__(self):
        return self

    def __exit__(self, _kind, _error, _traceback):
        return False


def _analyze_with_stubbed_llm(monkeypatch, tmp_path, policy, *, fail_cleanup=False):
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"synthetic placeholder")
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.pdf.footnotes = policy
    settings.llm.structure = True
    settings.llm.cleanup = fail_cleanup
    settings.llm.classification = False
    settings.llm.narration = False
    settings.llm.fallback_to_deterministic = fail_cleanup

    block = DocumentBlock(
        id="note-1",
        span_ids=[],
        text="Synthetic footnote.",
        page_index=0,
        kind="footnote",
        order=0,
    )
    extracted = SimpleNamespace(
        blocks=[block],
        spans=[],
        toc=[],
        page_sizes=[(612.0, 792.0)],
        title="Synthetic",
        author=None,
        warnings=["PDF inspection warning"],
    )
    captured = {}
    monkeypatch.setattr(pipeline, "extract_pdf", lambda *a, **k: extracted)
    monkeypatch.setattr(pipeline, "pagination_cleanup", lambda *a, **k: [])
    monkeypatch.setattr(pipeline, "create_provider", lambda *a, **k: _Provider())
    monkeypatch.setattr(pipeline, "CachedLLMProvider", lambda _provider, **kwargs: _provider)
    monkeypatch.setattr(
        pipeline,
        "detect_llm_headings",
        lambda *args, **kwargs: (set(), ["LLM heading requires manual review"]),
    )

    if fail_cleanup:

        def fail(*_args, **_kwargs):
            raise LLMError("Synthetic provider failure")

        monkeypatch.setattr(pipeline, "propose_llm_cleanup", fail)

    monkeypatch.setattr(
        pipeline,
        "propose_chapters",
        lambda *args, **kwargs: (
            [
                Chapter(
                    id="chapter-1",
                    number=1,
                    title="Synthetic Chapter",
                    start_block=0,
                    end_block=1,
                    confidence=1.0,
                )
            ],
            [],
        ),
    )
    monkeypatch.setattr(pipeline, "render_chapter_texts", lambda *args: None)
    monkeypatch.setattr(pipeline, "write_json", lambda *args: None)
    monkeypatch.setattr(
        pipeline,
        "write_manifest",
        lambda _path, manifest: captured.update(manifest=manifest),
    )
    pipeline.analyze_book(source, settings)
    return captured["manifest"]


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        ("inline", "Footnotes retained at their PDF reading positions"),
        ("omit", "Excluded 1 conservatively classified footnote"),
    ],
)
def test_llm_structure_keeps_footnote_policy_warning(
    monkeypatch,
    tmp_path,
    policy,
    expected,
):
    manifest = _analyze_with_stubbed_llm(monkeypatch, tmp_path, policy)
    assert manifest.warnings[0] == "PDF inspection warning"
    assert any(expected in warning for warning in manifest.warnings)
    assert "LLM heading requires manual review" in manifest.warnings
    if policy == "omit":
        assert any(edit.accepted and edit.block_id == "note-1" for edit in manifest.edits)


def test_later_llm_failure_preserves_footnote_warning_but_discards_llm_warning(
    monkeypatch,
    tmp_path,
):
    manifest = _analyze_with_stubbed_llm(
        monkeypatch,
        tmp_path,
        "inline",
        fail_cleanup=True,
    )
    assert any(
        "Footnotes retained at their PDF reading positions" in warning
        for warning in manifest.warnings
    )
    assert "LLM heading requires manual review" not in manifest.warnings
    assert "LLM provider failed; explicit deterministic fallback used" in manifest.warnings
