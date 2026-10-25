"""Source-span provenance must be complete and nonduplicated before narration."""

import pytest

from pdf2audiobook.document.structure import chapter_coverage_report
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock, SourceSpan


def manifest_with_spans(block_refs, *, span_count=None):
    if span_count is None:
        span_count = len(block_refs)
    return BookManifest(
        schema_version=3,
        input_sha256="a" * 64,
        title="Synthetic source",
        source_path="synthetic.pdf",
        spans=[
            SourceSpan(id=f"s{index}", page_index=0, text=f"Line {index}")
            for index in range(span_count)
        ],
        blocks=[
            DocumentBlock(
                id=f"b{index}",
                span_ids=list(refs),
                page_index=0,
                text=f"Line {index}",
            )
            for index, refs in enumerate(block_refs)
        ],
        chapters=[
            Chapter(
                id="c1",
                number=1,
                title="Full Book",
                start_block=0,
                end_block=len(block_refs),
                confidence=1.0,
            )
        ],
    )


def test_valid_one_to_one_span_mapping_is_covered():
    report = chapter_coverage_report(manifest_with_spans([["s0"], ["s1"]]))
    assert report["valid"] is True
    assert report["source_spans"] == 2
    assert report["covered_blocks"] == 2


def test_multiple_unique_spans_per_block_are_covered():
    report = chapter_coverage_report(manifest_with_spans([["s0", "s1"]], span_count=2))
    assert report["source_spans"] == 2
    assert report["covered_blocks"] == 1


@pytest.mark.parametrize(
    ("refs", "span_count", "message"),
    [
        ([["s0", "s0"]], 1, "assigned more than once"),
        ([["s0"], ["s0"]], 1, "assigned more than once"),
        ([["s0"]], 2, "unassigned source spans"),
        ([["s0", "not-in-source"]], 1, "missing source spans"),
        ([[]], 1, "no source span provenance"),
    ],
)
def test_missing_or_duplicate_provenance_fails_closed(refs, span_count, message):
    with pytest.raises(ExtractionError, match=message):
        chapter_coverage_report(manifest_with_spans(refs, span_count=span_count))
