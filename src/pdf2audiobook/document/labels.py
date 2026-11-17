"""Chapter and part labels, numerals and heading lines: the patterns the chapter steps share."""

from __future__ import annotations

import re

from pdf2audiobook.document.pagination import (
    _AMBIGUOUS_NUMERALS,
    _ROMAN_TITLE,
    _number_value,
)
from pdf2audiobook.models import DocumentBlock

CHAPTER_WORD = r"c(?:h|ii|li)apte[rek]"


HEADING = re.compile(
    rf"^(?:(?:{CHAPTER_WORD}|part)\s+(?:\d+|[ivxlcdm]+|one|two|three|four|five|six|"
    r"seven|eight|nine|ten)\b.*|prologue|epilogue|preface|introduction)$",
    re.IGNORECASE,
)


NUMBERED_LABEL = re.compile(
    rf"^(?:{CHAPTER_WORD}|part)\s+(?:\d+|[ivxlcdm]+|one|two|three|four|five|six|"
    r"seven|eight|nine|ten)\b",
    re.IGNORECASE,
)


ROMAN = re.compile(r"[IVXLCDM]+")


LABELLED_NUMBER = re.compile(rf"^(?i:{CHAPTER_WORD}|part|book|canto|section)\s+\S+$")


LABEL_PROSE = re.compile(rf"^(?i:{CHAPTER_WORD}|part)\s+\S+\s+[a-z]")


PAGE_REFERENCE_END = re.compile(r"[^\W\d_][\s.…·]*\s\d{1,4}$")


CHAPTER_TEXT_NAME = re.compile(r"\d{3,}\.txt")


WRAPPED_LINE_END = re.compile(r"[^\W\d_]-$")


PAGE_NUMBER = re.compile(r"^(?:\d{1,5}|[ivxlcdm]{1,10})$", re.IGNORECASE)


CANONICAL_ROMAN = re.compile(
    r"^M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})"
    r"(?:IX|IV|V?I{0,3})$"
)


def _label_key(text: str) -> str:
    """Compare chapter labels across OCR misreadings: "CHAPTEE  XI" is "chapter xi"."""
    words = text.casefold().split()
    if words and re.fullmatch(CHAPTER_WORD, words[0]):
        words[0] = "chapter"
    return _title_key(" ".join(words))


def _title_key(text: str) -> str:
    """Compare outline titles to headings ignoring case, spacing and trailing
    punctuation ("Chapter I" matches "CHAPTER I.")."""
    return " ".join(text.casefold().split()).rstrip(".:;, ")


_NUMBER_WORDS = {
    word: value
    for value, word in enumerate(
        "one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
        "fifteen sixteen seventeen eighteen nineteen".split(),
        start=1,
    )
}


_TENS_WORDS = {
    word: value * 10
    for value, word in enumerate(
        "twenty thirty forty fifty sixty seventy eighty ninety".split(), start=2
    )
}


LABEL_NUMBER = re.compile(
    rf"^(?i:{CHAPTER_WORD}|part)\s+([A-Za-z0-9]+(?:-[A-Za-z]+)?)(?:\s*[.:\-\u2013\u2014]\s*.*|\.)?$"
)


def _roman_value(token: str) -> int | None:
    token = token.upper()
    if not token or not CANONICAL_ROMAN.fullmatch(token):
        return None
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    for current, following in zip(token, token[1:] + " "):
        value = values[current]
        total += -value if following != " " and values[following] > value else value
    return total


def _ordinal_value(token: str) -> int | None:
    """Value of "12", "XII" or "twelve"/"twenty-one"; None for anything else."""
    token = token.strip().casefold()
    if token.isdecimal():
        return int(token) if len(token) <= 3 else None
    if token in _NUMBER_WORDS:
        return _NUMBER_WORDS[token]
    tens, _, ones = token.partition("-")
    if tens in _TENS_WORDS:
        return _TENS_WORDS[tens] + (_NUMBER_WORDS.get(ones, 0) if ones else 0)
    return _roman_value(token)


def label_key(text: str) -> tuple[str, int] | None:
    """("chapter", 12) for "Chapter 12"/"CHAPTER XII", ("part", 3) for "Part 3"."""
    stripped = text.strip()
    match = LABEL_NUMBER.match(stripped)
    value = _ordinal_value(match.group(1)) if match else None
    if value is None:
        return None
    return ("part" if stripped.casefold().startswith("part") else "chapter", value)


def label_number(text: str) -> int | None:
    """Number named by "Chapter 12", "CHAPTER XII", "Chapter Twelve" or "Part 3"."""
    key = label_key(text)
    return key[1] if key else None


_LEADER_PAGE_REF = re.compile(
    r"(?:\s*[.\u00b7\u2026]{2,}\s*|\s+[.\u00b7\u2026]\s+)(?:\d{1,4}|[ivxlcdm]{1,8})$",
    re.IGNORECASE,
)


def contents_label_title(text: str) -> str:
    """A contents line's chapter label without its leader dots and page reference."""
    return _LEADER_PAGE_REF.sub("", text.strip()).strip()


def bare_number(text: str) -> int | None:
    """Number of a line that is only a numeral ("12", "12." or capital "XII")."""
    token = text.strip().rstrip(".").strip()
    if token.isdecimal():
        return int(token) if len(token) <= 3 else None
    return _roman_value(token) if token.isupper() else None


CONTENTS_HEADINGS = frozenset({"contents", "table of contents"})


CONTENTS_PAGE_REF = re.compile(r"[\s.·…]+(?:\d{1,4}|[ivxlcdm]{1,8})$", re.IGNORECASE)


def _loose_key(text: str) -> str:
    """Letters and digits only, tolerating OCR-dropped spaces and stray marks
    ("THE SILLYJELLY-FISH", "‘THE TEA-KETTLE")."""
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def labelled_heading(text: str) -> bool:
    """A chapter/part/prologue label line, not prose that cites one."""
    stripped = text.strip()
    roman_title = _ROMAN_TITLE.fullmatch(stripped)
    if roman_title is not None and roman_title.group(1) in _AMBIGUOUS_NUMERALS:
        roman_title = None
    return roman_title is not None or (
        HEADING.match(text) is not None and len(text.split()) <= 12 and not LABEL_PROSE.match(text)
    )


def roman_sequence_heading_indices(blocks: list[DocumentBlock], skip: set[int]) -> set[int]:
    """One-letter numeral titles that sit beside a neighbouring Roman heading.

    "V. THE FOREST" is a chapter heading when "IV." or "VI." headings exist;
    "C. DICKENS" has no such neighbour and stays body text.
    """
    values: set[int] = set()
    ambiguous: dict[int, int] = {}
    for index, block in enumerate(blocks):
        if index in skip:
            continue
        match = _ROMAN_TITLE.fullmatch(block.text.strip())
        parsed = _number_value(match.group(1)) if match is not None else None
        if match is None or parsed is None:
            continue
        if match.group(1) in _AMBIGUOUS_NUMERALS:
            ambiguous[index] = parsed[0]
        else:
            values.add(parsed[0])
    return {index for index, value in ambiguous.items() if {value - 1, value + 1} & values}


def is_heading_line(text: str) -> bool:
    """Shared conservative classifier for extraction kind and chapter analysis."""
    return labelled_heading(text.strip())
