"""FX9 changed derived text, so analysis and chapter audio identities must differ (spec §9.9)."""

import pdf2audiobook.pipeline as pipeline
from pdf2audiobook.config import Settings
from pdf2audiobook.models import BookManifest, Chapter
from pdf2audiobook.pipeline import (
    CHAPTER_AUDIO_FINGERPRINT_NORMALIZATION_VERSION,
    _analysis_stage_fingerprints,
    chapter_audio_fingerprint,
)


def test_chapter_audio_identity_carries_the_fx9_narration_version():
    assert CHAPTER_AUDIO_FINGERPRINT_NORMALIZATION_VERSION == "narration-normalization-v3"
    manifest = BookManifest(
        schema_version=3, input_sha256="x", title="Book", source_path="book.pdf"
    )
    chapter = Chapter(id="c1", number=1, title="One", start_block=0, end_block=1, confidence=1)
    first = chapter_audio_fingerprint("A sentence.", Settings(), manifest, chapter)
    assert first == chapter_audio_fingerprint("A sentence.", Settings(), manifest, chapter)


def test_changing_narration_version_changes_computed_chapter_audio_fingerprint(monkeypatch):
    manifest = BookManifest(
        schema_version=3, input_sha256="x", title="Book", source_path="book.pdf"
    )
    chapter = Chapter(id="c1", number=1, title="One", start_block=0, end_block=1, confidence=1)
    before = chapter_audio_fingerprint("A sentence.", Settings(), manifest, chapter)
    monkeypatch.setattr(
        pipeline,
        "CHAPTER_AUDIO_FINGERPRINT_NORMALIZATION_VERSION",
        "test-different-version",
    )
    after = chapter_audio_fingerprint("A sentence.", Settings(), manifest, chapter)
    assert after != before


def test_extraction_fingerprint_is_the_bullet_list_generation():
    # Supersedes analysis-v23 (EPUB chapters): bulleted lines next to a matching
    # bullet are now classified as list blocks, so older extraction results are
    # not reused.
    # analysis-v26: lines inside figures and rule-bounded tables are classified figure_text,
    # and "Figure 3 A model" (no punctuation) counts as a caption. (v25: a repeated margin
    # line counts as a running head with a page number only when its number follows the pages.)
    stages = _analysis_stage_fingerprints("a" * 64, Settings(), None)
    from pdf2audiobook.workspace import fingerprint

    assert stages["extraction"] == fingerprint(
        "analysis-v26", "a" * 64, Settings().pdf.model_dump()
    )
    # chapter-detection-v6: numbered subsections stay in their section's chapter, the
    # body size is weighed by characters, LLM headings must be larger than the body, and
    # a line beside a heading (a margin stamp, the other column) is not above it.
    # (v5: a contents list continued on the next page no longer opens chapters.)
    assert stages["chapter-boundaries"] == fingerprint(
        "chapter-detection-v6",
        Settings().chapters.model_dump(exclude={"allow_single_chapter", "min_boundary_confidence"}),
    )


def test_llm_analysis_identity_carries_its_prompt_version(monkeypatch):
    # The cleanup and classification prompts and the equation window sizes changed what the
    # LLM steps produce, so earlier LLM analyses must not be reused.
    assert pipeline.LLM_ANALYSIS_VERSION == "llm-analysis-v2"
    before = _analysis_stage_fingerprints("a" * 64, Settings(), None)["llm-analysis"]
    monkeypatch.setattr(pipeline, "LLM_ANALYSIS_VERSION", "test-different-version")
    after = _analysis_stage_fingerprints("a" * 64, Settings(), None)["llm-analysis"]
    assert after != before
    disabled = Settings()
    disabled.llm.enabled = False
    assert _analysis_stage_fingerprints("a" * 64, disabled, None)["llm-analysis"] == (
        pipeline.fingerprint("disabled")
    )
