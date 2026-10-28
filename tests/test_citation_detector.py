"""Numeric citations are found precisely, and nothing else is (C2)."""

import pytest

from pdf2audiobook.audio.citations import citation_ranges, mask_citations


def _found(text: str) -> list[str]:
    return [text[start:end] for start, end in citation_ranges(text)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("shown in [13] earlier", ["[13]"]),
        ("models [35, 2, 5].", ["[35, 2, 5]"]),
        ("see [1-3] for more", ["[1-3]"]),
        ("see [1–3] for more", ["[1–3]"]),
        ("both [4; 7] agree", ["[4; 7]"]),
        ("spaced [ 8 ] out", ["[ 8 ]"]),
        ("at the start [9] of it", ["[9]"]),
        ("[13] opens the paragraph", ["[13]"]),
        ("(see [13])", ["[13]"]),
        ("quoted “[7]”", ["[7]"]),  # an opening quote is valid context
        ("split across [35,\n2] lines", ["[35,\n2]"]),
        ("two [1] and [2, 3] here", ["[1]", "[2, 3]"]),
        ("range and list [1-3, 7]", ["[1-3, 7]"]),
    ],
)
def test_citations_are_found(text: str, expected: list[str]) -> None:
    assert _found(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "an array a[1] element",  # attached to a word
        "index x[i] here",  # letters
        "a note [see 13] here",  # words inside
        "too long [1234] here",  # more than three digits
        "backwards [3-1] range",  # descending range
        "equal [2-2] range",  # not an ascending pair
        "zero [0] here",  # citations start at one
        "padded [01] here",  # leading zero
        "empty [] here",
        "dangling [1,] comma",
        "missing separator [1 2] here",
        "author year (Vaswani et al., 2017) here",  # out of scope
        "year only [2017a] here",
        "models[5] attached",  # attached to a word, conservatively not a citation
        "unterminated [13 here",
        "blank line inside [13\n\n14] here",
    ],
)
def test_other_bracketed_text_is_not_a_citation(text: str) -> None:
    assert _found(text) == []
    assert mask_citations(text) == text


@pytest.mark.parametrize(
    ("text", "dotted"),  # "\u00b7" stands for a blank so the expected length is visible
    [
        ("shown in [13] earlier", "shown in\u00b7\u00b7\u00b7\u00b7\u00b7\u00b7earlier"),
        ("translation [38].", "translation.\u00b7\u00b7\u00b7\u00b7\u00b7"),
        ("see (also [13])", "see (also)\u00b7\u00b7\u00b7\u00b7\u00b7"),
        ("[13] opens", "\u00b7\u00b7\u00b7\u00b7\u00b7opens"),
        ("as shown [13], and", "as shown,\u00b7\u00b7\u00b7\u00b7\u00b7\u00b7and"),
        ("a [1][2] b", "a\u00b7\u00b7\u00b7\u00b7\u00b7\u00b7\u00b7\u00b7b"),
    ],
)
def test_masking_blanks_citations_and_moves_closing_punctuation_left(
    text: str, dotted: str
) -> None:
    masked = mask_citations(text)
    assert masked == dotted.replace("\u00b7", " ")
    assert len(masked) == len(text)


def test_masking_never_changes_the_length_or_other_characters() -> None:
    text = "Intro [1].\n\nThe model [35, 2, 5] uses x[i] and a [3-4]; done [7]!\n"
    result = mask_citations(text)
    assert len(result) == len(text)
    kept = [i for i, (a, b) in enumerate(zip(text, result)) if a != b]
    assert all(text[i] in "[]0123456789,;- .!" for i in kept)
    assert "x[i]" in result


def test_masking_is_idempotent_and_leaves_citation_free_text_alone() -> None:
    text = "Plain prose with no citations at all."
    assert mask_citations(text) == text
    once = mask_citations("A [1] B [2].")
    assert mask_citations(once) == once


@pytest.mark.parametrize(
    "text",
    [
        "x ∈ [1, 5].",
        "p = [2, 3]",
        "a ≤ [4]",
        "y ≥ [7]",
        "z < [2]",
        "n > [3]",
        "q ≈ [2]",
        "m × [3]",
        "r =\n[2, 3]",
    ],
)
def test_a_group_after_a_math_relation_is_an_interval_not_a_citation(text: str) -> None:
    assert citation_ranges(text) == []
    assert mask_citations(text) == text


@pytest.mark.parametrize(
    "text", ["as shown in [1, 5].", "results [13]", "see also [4; 7]", "so x [2]"]
)
def test_prose_context_still_makes_a_citation(text: str) -> None:
    assert len(citation_ranges(text)) == 1
