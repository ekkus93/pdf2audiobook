"""Numeric citations such as ``[13]`` or ``[35, 2, 5]``, which read badly aloud.

Detection is deliberately narrow: only bracketed integer lists and ascending ranges
that follow whitespace or an opening bracket or quote. Anything that might be code,
an index or prose (``a[1]``, ``x[i]``, ``[see 13]``) is left alone.
"""

from __future__ import annotations

import re

_NUMBER = r"[1-9][0-9]{0,2}"
_SPACE = r"[ \t\r\n]*"
_ITEM = rf"{_NUMBER}(?:{_SPACE}[-–]{_SPACE}{_NUMBER})?"
# Context before "[": the start of the text, whitespace, or an opening bracket/quote.
_CONTEXT = "(?<![^\\s(\\[{\"'“‘])"
CITATION = re.compile(_CONTEXT + rf"\[{_SPACE}({_ITEM}(?:{_SPACE}[,;]{_SPACE}{_ITEM})*){_SPACE}\]")
_RANGE = re.compile(rf"({_NUMBER}){_SPACE}[-–]{_SPACE}({_NUMBER})")
_BLANK_LINE = re.compile(r"\n[ \t]*\n|\r[ \t]*\r|\r\n[ \t]*\r\n")
# Punctuation that follows a citation and belongs to the word before it.
_CLOSERS = frozenset(".,;:!?)}\"'’”")


def citation_ranges(text: str) -> list[tuple[int, int]]:
    """Character ranges of citation groups, in order."""
    found: list[tuple[int, int]] = []
    for match in CITATION.finditer(text):
        if _BLANK_LINE.search(match.group()):
            continue  # a citation never spans a paragraph break
        if any(int(low) >= int(high) for low, high in _RANGE.findall(match.group(1))):
            continue  # ranges are ascending pairs
        found.append(match.span())
    return found


def mask_citations(text: str) -> str:
    """Blank citations without changing the length or any other character's offset.

    Punctuation that directly followed a citation moves left into the gap, so
    "translation [38]." is spoken "translation." rather than "translation .".
    """
    for _ in range(4):  # adjacent groups such as "[1][2]" appear after the first pass
        ranges = citation_ranges(text)
        if not ranges:
            break
        characters = list(text)
        for start, end in ranges:
            lead = start
            while lead > 0 and text[lead - 1] in " \t":
                lead -= 1
            tail = end
            while tail < len(text) and text[tail] in _CLOSERS:
                tail += 1
            punctuation = text[end:tail]
            if lead < start and punctuation:
                characters[lead:tail] = punctuation + " " * (tail - lead - len(punctuation))
            else:
                characters[start:end] = " " * (end - start)
        text = "".join(characters)
    return text
