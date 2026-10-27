"""Context-aware list marker classification."""

import re

_LIST_MARKER = re.compile(
    r"^\s*(?P<marker>\d{1,3}[.)]|[ivxlcdm]{2,}[.)]|[A-Za-z][.)]|[•*])\s+(?P<rest>\S.*)$",
    re.IGNORECASE,
)
_ROMAN_LIST_VALUES = {
    marker: value
    for value, marker in enumerate(("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"), 1)
}


def _list_marker(text: str) -> tuple[str, str] | None:
    match = _LIST_MARKER.match(text)
    if match is None:
        return None
    marker = match.group("marker")[:-1]
    rest = match.group("rest")
    # A. Smith and B. Jones are prose initials, not alphabetic list items.
    if len(marker) == 1 and marker.isalpha() and re.match(r"[A-Z][a-z]+\b", rest):
        return None
    if marker.isdigit() and len(marker) >= 3 and text.lstrip().startswith(marker + ")"):
        return None
    return marker, rest


def _sequential_markers(first: str, second: str) -> bool:
    if first.isdigit() and second.isdigit():
        return int(second) == int(first) + 1
    if len(first) == len(second) == 1 and first.isalpha() and second.isalpha():
        return ord(second.lower()) == ord(first.lower()) + 1
    if first in {"•", "*"} or second in {"•", "*"}:
        return first == second
    left, right = first.casefold(), second.casefold()
    return (
        left in _ROMAN_LIST_VALUES
        and right in _ROMAN_LIST_VALUES
        and _ROMAN_LIST_VALUES[right] == _ROMAN_LIST_VALUES[left] + 1
    )


def is_list_line(
    text: str, *, previous_text: str | None = None, next_text: str | None = None
) -> bool:
    """Classify a line as part of a sequential list run, using adjacent lines."""
    current = _list_marker(text)
    if current is None:
        return False
    marker, _ = current
    previous = _list_marker(previous_text) if previous_text is not None else None
    following = _list_marker(next_text) if next_text is not None else None
    if previous is not None and _sequential_markers(previous[0], marker):
        return True
    if following is not None and _sequential_markers(marker, following[0]):
        return True
    # Day-of-month and page-number wraps are prose unless the marker continues
    # a sequential run on the adjacent line.
    if previous_text is not None and re.search(r"\b(?:may|page)\s*$", previous_text, re.I):
        return False
    # Preserve the public helper's historical candidate behavior when callers
    # have no neighboring lines. Extraction and reflow always provide context.
    return previous_text is None and next_text is None
