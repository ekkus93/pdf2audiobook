"""Page-number values, running titles and folios: what a printed page number or running head looks like."""

from __future__ import annotations

import re
import unicodedata

CHAPTER_WORD = r"c(?:h|ii|li)apte[rek]"


LABELLED_NUMBER = re.compile(rf"^(?i:{CHAPTER_WORD}|part|book|canto|section)\s+\S+$")


PAGE_NUMBER = re.compile(r"^(?:\d{1,5}|[ivxlcdm]{1,10})$", re.IGNORECASE)


PAGE_NUMBER_EDGE_TIE_TOLERANCE_PT = 2.0


CANONICAL_ROMAN = re.compile(
    r"^M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})"
    r"(?:IX|IV|V?I{0,3})$"
)


def _number_value(raw: str) -> tuple[int, str] | None:
    """Only canonical Roman or short Arabic numerals count as page numbers."""
    if raw.isascii() and raw.isdecimal() and len(raw) <= 5:
        return int(raw), "arabic"
    roman = raw.upper()
    if not roman or not CANONICAL_ROMAN.fullmatch(roman):
        return None
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    for index, symbol in enumerate(roman):
        number = values[symbol]
        total += (
            -number if index + 1 < len(roman) and (number < values[roman[index + 1]]) else number
        )
    return total, "roman"


_ROMAN_TITLE = re.compile(r"([IVXLCDM]{1,8})[.)]\s+[A-Z][A-Z\s'’:-]{2,80}")


_AMBIGUOUS_NUMERALS = frozenset("CDLMVX")


def _wordlike(text: str) -> bool:
    """Scan noise (rules, stray quotes, digit runs, mixed-script mojibake) is not a heading."""
    letters = [char for char in text if char.isalpha()]
    if len(letters) < 2 or len(letters) < 0.6 * sum(not char.isspace() for char in text):
        return False
    # A real title is written in one script; OCR failures mix Latin with
    # Cyrillic, Oriya and similar look-alike glyphs.
    scripts = {unicodedata.name(char, "UNKNOWN").split()[0] for char in letters}
    return len(scripts) == 1


def _aligned_number_positions(first: float, second: float) -> bool:
    """Allow fixed placement or mirrored odd/even page-number positions."""
    return abs(first - second) <= 0.06 or abs(first + second - 1) <= 0.06


RUNNING_FOLIO = re.compile(
    r"^(?:(?P<lead>\d{1,4}|[ivxlcdm]{1,8})\s+(?P<after>\S.*)|"
    r"(?P<before>.*\S)\s+(?P<trail>\d{1,4}|[ivxlcdm]{1,8}))$",
    re.IGNORECASE,
)


def _titled(text: str) -> bool:
    """A running title has a real word; "x dx" or "dy dx" from a formula does not."""
    words = re.findall(r"[^\W\d_]{3,}", text)
    return _wordlike(text) and bool(words) and sum(len(word) for word in words) >= 4


def _running_parts(text: str) -> tuple[str, str | None]:
    """Split a margin line into its title key and an embedded folio, if any.

    "OF THE ROMAN EMPIRE 27" and "30 THE DECLINE AND FALL" are a repeated
    running title plus the page number. A numbered chapter/part label keeps
    its numeral: "CHAPTER II" is a different title from "CHAPTER III".
    """
    raw = " ".join(text.split())
    match = RUNNING_FOLIO.match(raw)
    if match is None or LABELLED_NUMBER.match(raw):
        return raw.casefold(), None
    title = match.group("after") or match.group("before")
    folio = match.group("lead") or match.group("trail")
    if not _titled(title):
        return raw.casefold(), None
    return title.casefold(), folio


def _aligned_folios(first: tuple[float, float] | None, second: tuple[float, float] | None) -> bool:
    """Folios align on the paper, or relative to sideways-drifting scanned text.

    None marks a folio embedded in a running title, whose repetition is the
    positional evidence.
    """
    if first is None or second is None:
        return True
    return any(_aligned_number_positions(a, b) for a, b in zip(first, second))
