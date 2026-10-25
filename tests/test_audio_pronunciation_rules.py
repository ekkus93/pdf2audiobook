"""Pronunciation replacement keeps sentence punctuation exactly once (R68)."""

import pytest

from pdf2audiobook.audio import chunk_source_ranges, split_sentences

KEYS = {
    "dr.": "Doctor",
    "u.s.": "United States",
    "c++": "seeplus",
    "hermione": "Her-my-oh-nee",
    "etc.": "and so on",
}


def _speak(source, pronunciations=KEYS):
    chunks = split_sentences(source, pronunciations=pronunciations)
    assert chunk_source_ranges(source, chunks, pronunciations=pronunciations)
    return " ".join(chunks)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Dr. Watson arrived.", "Doctor Watson arrived."),
        ("the U.S. army left.", "the United States army left."),
        ("They went to the U.S.", "They went to the United States."),
        ("Dr. U.S., (C++) done.", "Doctor United States, (seeplus) done."),
        ("Hermione smiled.", "Her-my-oh-nee smiled."),
        ("She was Hermione.", "She was Her-my-oh-nee."),
        ("Hermione...", "Her-my-oh-nee..."),
        ("Hermione…", "Her-my-oh-nee..."),
        ("Then Hermione... left.", "Then Her-my-oh-nee... left."),
        ("Cats, dogs, etc. and more.", "Cats, dogs, and so on and more."),
    ],
)
def test_pronunciation_punctuation_is_kept_exactly_once(source, expected):
    assert _speak(source) == expected


def test_ellipsis_after_a_replaced_word_is_not_collapsed_to_a_period():
    assert split_sentences("hello...", pronunciations={"hello": "hullo"}) == ["hullo..."]
