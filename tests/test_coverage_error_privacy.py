"""Manifest coverage errors never echo attacker-controlled source identifiers."""

import pytest

from pdf2audiobook.document.structure import chapter_coverage_report
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.models import BookManifest, Chapter, CleanupEdit, DocumentBlock, SourceSpan

PRIVATE = "SYNTHETIC_PRIVATE_MANIFEST_IDENTIFIER_642"


def _manifest() -> BookManifest:
    return BookManifest(
        schema_version=3,
        input_sha256="a" * 64,
        title="Synthetic",
        source_path="fixture.pdf",
        spans=[SourceSpan(id="span-1", page_index=0, text="A synthetic passage.")],
        blocks=[
            DocumentBlock(
                id="block-1",
                span_ids=["span-1"],
                page_index=0,
                text="A synthetic passage.",
            )
        ],
        chapters=[
            Chapter(
                id="chapter-1",
                number=1,
                title="Test",
                start_block=0,
                end_block=1,
                confidence=1.0,
            )
        ],
    )


@pytest.mark.parametrize(
    ("case", "diagnostic"),
    [
        ("missing_provenance", "Source block has no source span provenance"),
        ("missing_span", "Source block references missing source spans"),
        ("duplicate_span", "Source span is assigned more than once"),
        ("missing_edit_block", "Cleanup edit references missing source block"),
        ("mismatched_original", "Cleanup edit original does not match source block"),
        ("duplicate_edit", "Multiple accepted edits for source block"),
    ],
)
def test_coverage_error_redacts_untrusted_ids(case: str, diagnostic: str) -> None:
    manifest = _manifest()
    if case == "missing_provenance":
        manifest.blocks[0] = manifest.blocks[0].model_copy(update={"id": PRIVATE, "span_ids": []})
    elif case == "missing_span":
        manifest.blocks[0] = manifest.blocks[0].model_copy(
            update={"id": PRIVATE, "span_ids": [PRIVATE]}
        )
    elif case == "duplicate_span":
        manifest.blocks.append(
            DocumentBlock(
                id=PRIVATE,
                span_ids=["span-1"],
                page_index=0,
                text="Second synthetic passage.",
            )
        )
        manifest.chapters[0] = manifest.chapters[0].model_copy(update={"end_block": 2})
        manifest.spans[0] = manifest.spans[0].model_copy(update={"id": PRIVATE})
        manifest.blocks[0] = manifest.blocks[0].model_copy(update={"span_ids": [PRIVATE]})
        manifest.blocks[1] = manifest.blocks[1].model_copy(update={"span_ids": [PRIVATE]})
    else:
        manifest.blocks[0] = manifest.blocks[0].model_copy(update={"id": PRIVATE})
        original = "A synthetic passage."
        if case == "missing_edit_block":
            manifest.edits = [
                CleanupEdit(
                    block_id="unknown-" + PRIVATE,
                    original=original,
                    replacement="",
                    reason="test",
                    confidence=1.0,
                    accepted=True,
                )
            ]
        else:
            edit = CleanupEdit(
                block_id=PRIVATE,
                original="incorrect" if case == "mismatched_original" else original,
                replacement="",
                reason="test",
                confidence=1.0,
                accepted=True,
            )
            manifest.edits = [edit, edit.model_copy()] if case == "duplicate_edit" else [edit]

    with pytest.raises(ExtractionError, match=diagnostic) as raised:
        chapter_coverage_report(manifest)
    assert PRIVATE not in str(raised.value)


def test_valid_coverage_still_reports_exact_once_assignment() -> None:
    report = chapter_coverage_report(_manifest())
    assert report["valid"] is True
    assert report["source_spans"] == 1
    assert report["covered_blocks"] == 1
