"""Paragraph pauses preserve provenance across newline conventions."""

import pytest

from pdf2audiobook.audio import chunk_source_ranges, split_sentences


@pytest.mark.parametrize(
    "separator",
    ["\n\n", "\r\n\r\n", "\r\r", "\r\n\n", "\n  \r\n", "\r\n \r"],
)
def test_paragraph_boundaries_include_cr_only_and_mixed_newlines(separator):
    first = "First paragraph is spoken."
    second = "Second paragraph is spoken."
    source = first + separator + second
    chunks = split_sentences(source)
    assert chunks == [first, second]
    assert chunk_source_ranges(source, chunks) == [
        (0, len(first), False),
        (len(first) + len(separator), len(source), True),
    ]


@pytest.mark.parametrize("single_break", ["\n", "\r", "\r\n"])
def test_single_line_endings_are_soft_wraps_not_paragraph_pauses(single_break):
    source = "One line of narration" + single_break + "continues without a paragraph."
    chunks = split_sentences(source)
    assert chunks == ["One line of narration continues without a paragraph."]
    assert chunk_source_ranges(source, chunks) == [
        (0, len(source), False),
    ]
