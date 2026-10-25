"""Conservative pagination removal and chapter-boundary detection.

Raw blocks are immutable. Cleanup decisions are stored as audited edits.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from pdf2audiobook.config import Chapters as ChapterSettings
from pdf2audiobook.config import Pdf as PdfSettings
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.models import (
    BookManifest,
    Chapter,
    CleanupEdit,
    DocumentBlock,
    generated_chapter_fingerprint,
)


@dataclass
class ChapterProposal:
    chapters: list[Chapter]
    warnings: list[str]
    review_reasons: set[str]

    def __iter__(self) -> Iterator[list]:
        # Preserve the established ``chapters, warnings = propose_chapters(...)`` API.
        yield self.chapters
        yield self.warnings


# "Chapter" including common scan misreadings (CHAPTEE, CHAPTEK, CIIAPTER).
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
# "Chapter IV regarding ..." is a sentence that cites a chapter, not a label.
LABEL_PROSE = re.compile(rf"^(?i:{CHAPTER_WORD}|part)\s+\S+\s+[a-z]")
# A contents line ends with its page reference ("Death of Niger ... 120").
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


CONTENTS_HEADINGS = frozenset({"contents", "table of contents"})
CONTENTS_PAGE_REF = re.compile(r"[\s.·…]+(?:\d{1,4}|[ivxlcdm]{1,8})$", re.IGNORECASE)


def _loose_key(text: str) -> str:
    """Letters and digits only, tolerating OCR-dropped spaces and stray marks
    ("THE SILLYJELLY-FISH", "‘THE TEA-KETTLE")."""
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def _printed_contents(
    blocks: list[DocumentBlock], omitted: set[str], typical_size: float | None
) -> tuple[set[int], dict[int, str]]:
    """Find a printed contents page and the unique later headings it lists.

    Returns the contents-page line indices and {later heading index: title}.
    Titles are trusted only when at least two entries match uniquely.
    """
    start = next(
        (
            i
            for i, block in enumerate(blocks)
            if block.id not in omitted and _title_key(block.text) in CONTENTS_HEADINGS
        ),
        None,
    )
    if start is None:
        return set(), {}

    # Entries and their headings are at least body size; smaller lines are
    # running heads, column labels or footnotes.
    def heading_size(index: int) -> bool:
        size = blocks[index].font_size
        return typical_size is None or size is None or float(size) >= typical_size * 0.95

    contents_page = blocks[start].page_index
    lines = {start}
    # (block index, normalized entry, tentative). Entries on the following
    # page are tentative: that page may instead open the first chapter, so
    # they count only if they name a later heading other than themselves.
    entries: list[tuple[int, str, bool]] = []
    for i in range(start + 1, len(blocks)):
        block = blocks[i]
        if block.page_index > contents_page + 1:
            break
        if block.id in omitted:
            continue
        tentative = block.page_index != contents_page
        text = block.text.rstrip()
        if tentative and (
            len(text.split()) > 10
            or text.endswith((".", "?", "!"))
            and not CONTENTS_PAGE_REF.search(text)
        ):
            break
        if not tentative:
            lines.add(i)
        entry = _title_key(CONTENTS_PAGE_REF.sub("", text))
        if (
            heading_size(i)
            and _loose_key(entry)
            and not entry.isdecimal()
            and not PAGE_NUMBER.match(entry)
        ):
            entries.append((i, entry, tentative))
    after = max(lines) + 1

    # Later heading lines, alone or joined with the next line on the same page,
    # since titles may wrap differently on the contents page and in the body.
    # Exact keys are tried first; letters-only keys tolerate OCR noise but
    # collide more easily with body text, so they are only a fallback.
    exact: dict[str, list[tuple[int, int]]] = defaultdict(list)
    loose: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for i in range(after, len(blocks)):
        if blocks[i].id in omitted or not heading_size(i):
            continue
        texts = [(blocks[i].text, 1)]
        j = i + 1
        if (
            j < len(blocks)
            and blocks[j].id not in omitted
            and blocks[j].page_index == blocks[i].page_index
            and heading_size(j)
        ):
            texts.append((f"{blocks[i].text} {blocks[j].text}", 2))
        for text, width in texts:
            exact[_title_key(text)].append((i, width))
            loose[_loose_key(text)].append((i, width))

    def unique(key: str, own: set[int]) -> tuple[int, int] | None:
        for spans, normalized in ((exact, _title_key(key)), (loose, _loose_key(key))):
            found = [span for span in spans.get(normalized, []) if span[0] not in own]
            if len(found) == 1:
                return found[0]
        return None

    titles: dict[int, str] = {}
    position = 0
    while position < len(entries):
        own_index, key, tentative = entries[position]
        own = {own_index}
        match = None
        consumed = 1
        if position + 1 < len(entries):
            next_index, next_key, next_tentative = entries[position + 1]
            match = unique(f"{key} {next_key}", own | {next_index})
            if match is not None:
                consumed = 2
                tentative = tentative or next_tentative
        if match is None:
            match = unique(key, own)
        if match is None or match[0] <= own_index:
            position += 1
            continue
        index, width = match
        if tentative:
            lines.update(entries[k][0] for k in range(position, position + consumed))
        titles[index] = " ".join(blocks[k].text.strip() for k in range(index, index + width))
        position += consumed
    return lines, titles if len(titles) >= 2 else {}


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
# One-letter numerals double as initials ("C. DICKENS", "M. LEBLANC"), so they
# only count as headings beside neighbouring numerals or by typography.
_AMBIGUOUS_NUMERALS = frozenset("CDLMVX")


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


def _valid_bbox(box: object) -> bool:
    """Use only finite, ordered PDF coordinates as cleanup evidence."""
    if not isinstance(box, (tuple, list)) or len(box) != 4:
        return False
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or abs(value) > 1_000_000
        or not math.isfinite(value)
        for value in box
    ):
        return False
    return box[0] < box[2] and box[1] < box[3]


def _adjacent_body_line(
    block: DocumentBlock,
    page_blocks: list[DocumentBlock],
    band: str,
) -> bool:
    """Treat close, horizontally aligned margin lines as possible body prose.

    A repeated opening sentence, dialogue line or list marker can occur within
    the nominal header/footer band. Without whitespace separating it from the
    body, deletion is unsafe even when it repeats on multiple pages.
    """
    if block.bbox is None or not _valid_bbox(block.bbox):
        return False
    x0, y0, x1, y1 = block.bbox
    line_height = max(1.0, y1 - y0)
    numeral = PAGE_NUMBER.fullmatch(block.text.strip()) is not None
    for other in page_blocks:
        if (
            other.id == block.id
            or other.bbox is None
            or not _valid_bbox(other.bbox)
            or not other.text.strip()
        ):
            continue
        ox0, oy0, ox1, oy1 = other.bbox
        # A running head set in much larger type than the line beside it is
        # a separate element, not the first line of a paragraph.
        if (
            block.font_size is not None
            and other.font_size is not None
            and block.font_size >= 1.4 * other.font_size
        ):
            continue
        if band == "header":
            gap = oy0 - y1
        else:
            gap = y0 - oy1
        if not (-0.2 * line_height <= gap <= 1.6 * line_height):
            continue
        # A centered folio/title and left-aligned body line are separate
        # regions. Matching indentation or substantial horizontal overlap
        # is stronger evidence that the two lines form one body paragraph.
        # A list label shares the body's indentation almost exactly; a
        # centered folio under a centered citation only roughly does.
        indent = max(4.0, 0.5 * line_height) if numeral else max(18.0, 1.5 * line_height)
        if abs(ox0 - x0) <= indent:
            return True
        # A lone folio sits under or over a full-width line, so it always
        # overlaps it; only matching indentation ties a numeral to the body.
        # Numerals still need a cross-page sequence before removal.
        if numeral:
            continue
        x_overlap = min(x1, ox1) - max(x0, ox0)
        narrow = max(1.0, min(x1 - x0, ox1 - ox0))
        if x_overlap >= 0.5 * narrow:
            return True
    return False


def pagination_cleanup(
    blocks: list[DocumentBlock],
    sizes: list[tuple[float, float]],
    settings: PdfSettings,
    *,
    page_labels: list[str | None] | None = None,
    warnings: list[str] | None = None,
    review_reasons: set[str] | None = None,
) -> list[CleanupEdit]:
    """Remove only corroborated pagination patterns confined to margin bands."""
    candidates: dict[str, tuple[DocumentBlock, str]] = {}
    text_occurrences: dict[tuple[str, str], list[tuple[int, float, float]]] = defaultdict(list)
    numbered: dict[str, list[tuple[int, int, tuple[float, float] | None, str]]] = defaultdict(list)
    vertical_positions: dict[tuple[str, int, int, str], list[float]] = defaultdict(list)
    blocks_by_page: dict[int, list[DocumentBlock]] = defaultdict(list)
    body_text: set[str] = set()

    def valid_page(page_index: int) -> bool:
        # Treat untrusted/malformed page sizes as missing evidence. In
        # particular, isfinite() raises for strings and huge Python integers.
        if not 0 <= page_index < len(sizes):
            return False
        dimensions = sizes[page_index]
        if not isinstance(dimensions, (tuple, list)) or len(dimensions) != 2:
            return False
        return all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and 0 < value <= 1_000_000
            and math.isfinite(value)
            for value in dimensions
        )

    # Scanned pages drift sideways; measure folio placement against each
    # page's text extent rather than the paper edge.
    extents: dict[int, tuple[float, float]] = {}
    for block in blocks:
        blocks_by_page[block.page_index].append(block)
        if block.bbox and _valid_bbox(block.bbox):
            left, right = extents.get(block.page_index, (block.bbox[0], block.bbox[2]))
            extents[block.page_index] = (min(left, block.bbox[0]), max(right, block.bbox[2]))

    def positions(block: DocumentBlock) -> tuple[float, float]:
        """Horizontal center relative to the paper and to the page's text."""
        assert block.bbox is not None
        center = (block.bbox[0] + block.bbox[2]) / 2
        left, right = extents.get(block.page_index, (0.0, 0.0))
        paper = center / sizes[block.page_index][0]
        if right - left >= 0.4 * sizes[block.page_index][0]:
            return paper, (center - left) / (right - left)
        return paper, paper

    def page_label_matches(page: int, value: int, notation: str) -> bool:
        if page_labels is None or page >= len(page_labels) or page_labels[page] is None:
            return True
        parsed = _number_value(str(page_labels[page]).strip())
        return parsed is None or parsed == (value, notation)

    # Titles repeated in a margin band on three or more pages are running
    # heads, whether or not a folio shares their line.
    title_pages: dict[tuple[str, str], set[int]] = defaultdict(set)
    for block in blocks:
        if not block.bbox or not _valid_bbox(block.bbox) or not valid_page(block.page_index):
            continue
        height = sizes[block.page_index][1]
        if block.bbox[1] >= 0.12 * height and block.bbox[3] <= 0.88 * height:
            body_text.add(" ".join(block.text.split()).casefold())
        elif block.bbox[3] < 0.12 * height or block.bbox[1] > 0.88 * height:
            text = block.text.strip()
            # Only short, unpunctuated title-like lines can be running heads.
            if len(text.split()) < 8 and not text.endswith((".", "?", "!", ",", ";", ":")):
                band_name = "header" if block.bbox[3] < 0.12 * height else "footer"
                title_pages[(band_name, _running_parts(text)[0])].add(block.page_index)
    running_titles = {key for key, pages in title_pages.items() if len(pages) >= 3}
    for block in blocks:
        if not block.bbox or not _valid_bbox(block.bbox) or not valid_page(block.page_index):
            continue
        height = sizes[block.page_index][1]
        top, bottom = block.bbox[1], block.bbox[3]
        band = "header" if bottom < height * 0.12 else ("footer" if top > height * 0.88 else None)
        if not band:
            continue
        raw = block.text.strip()
        val, embedded_folio = _running_parts(raw)
        running_title = (band, val) in running_titles
        # Fail closed when the apparent margin element is continuous with
        # nearby body text; repeated dialogue and list labels are not folios.
        # A title repeated on three or more pages with its folio is not.
        if (
            not (running_title and embedded_folio is not None)
            and _adjacent_body_line(block, blocks_by_page[block.page_index], band)
            and block.kind != "footnote"
        ):
            continue
        # Fail closed on standalone quotations, numbered list markers and
        # headings. These can legitimately occur in a page's margin band.
        # A heading-styled line repeated as a running head is the exception.
        if block.kind in {"list", "table", "footnote", "caption", "equation"}:
            continue
        if block.kind == "heading" and not running_title:
            continue
        if raw.startswith(
            (
                '"',
                "'",
                "“",
                "‘",
                "«",
                "‹",
                "„",
                "‚",
                "「",
                "『",
                "《",
                "•",
                "—",
                "–",
                "(",
                "[",
            )
        ):
            continue
        if raw.startswith(("- ", "− ")):
            # Hyphen-led dialogue is substantive even when it repeats in margins.
            continue
        # A closing quote or unfinished dialogue clause is also prose, not
        # a title/folio, even when a short fragment repeats in a margin.
        if raw.endswith(
            (
                '"',
                "'",
                "”",
                "’",
                "»",
                "›",
                "“",
                "‘",
                "」",
                "』",
                "》",
                ",",
                ";",
                "—",
            )
        ):
            continue
        # Short one-word dialogue or complete sentences can recur in page
        # margins; punctuation is stronger evidence of prose than repetition
        # is evidence of a running title. Fail closed instead of deleting it.
        if raw.endswith((".", "?", "!", "…")):
            continue
        # A repeated dialogue/speaker label or chapter-and-verse reference
        # can be isolated at the top or bottom of multiple pages. Repetition
        # is not sufficient evidence to delete these source text blocks.
        if raw.endswith((":", "：")) or re.search(r"\b\d{1,3}:\d{1,3}\b", raw):
            continue
        # A phrase appearing in the interior of any page is substantive text
        # somewhere in the book; do not delete identical margin occurrences.
        # Folio numerals are exempt: contents pages and cross-references
        # repeat them in body text, and they still need a page sequence.
        # A heading-styled running title, or one carrying its folio, also
        # appears once in the body as its section's own heading; repetition
        # on three or more margins outweighs that. Plain phrases stay.
        styled_title = running_title and (block.kind == "heading" or embedded_folio is not None)
        if (
            " ".join(raw.split()).casefold() in body_text
            and not PAGE_NUMBER.fullmatch(raw)
            and not styled_title
        ):
            continue
        # A full sentence or extended prose in the margin is not safe to
        # classify as a running title based on repetition alone.
        if len(raw.split()) >= 8 or (len(raw.split()) >= 3 and raw.endswith((".", "?", "!", "…"))):
            continue
        # Isolated list labels can repeat at page starts without being headers.
        if re.match(r"^(?:\(?\d{1,3}|[A-Za-z]|[IVXLCDMivxlcdm]{1,7})[.)](?:\s|$)", raw):
            continue
        # Standalone numerals may be section headings or list labels. Large
        # display type is not a folio; a same-line continuation suggests a
        # numbered list rather than a page number.
        beside_title = False
        if PAGE_NUMBER.fullmatch(raw):
            if block.font_size is not None and block.font_size > 14:
                continue
            same_line = [
                other
                for other in blocks_by_page[block.page_index]
                if other.id != block.id
                and other.bbox is not None
                and _valid_bbox(other.bbox)
                and other.text.strip()
                and other.bbox[0] >= block.bbox[2]
                and 0 <= other.bbox[0] - block.bbox[2] <= sizes[block.page_index][0] * 0.12
                and abs(other.bbox[1] - block.bbox[1]) <= max(5.0, block.bbox[3] - block.bbox[1])
            ]
            # "28   THE DECLINE AND FALL": a folio beside a running title,
            # rather than a list number beside its item.
            beside_title = bool(same_line) and all(
                (band, _running_parts(other.text)[0]) in running_titles for other in same_line
            )
            if same_line and not beside_title:
                continue
        # A lone numeric line at ordinary body indentation is not sufficient
        # evidence of pagination, even if another page starts with "2".
        if PAGE_NUMBER.fullmatch(raw):
            if not beside_title and not any(
                position <= 0.09 or position >= 0.91 or 0.38 <= position <= 0.62
                for position in positions(block)
            ):
                continue
        candidates[block.id] = (block, band)
        width = sizes[block.page_index][0]
        if width > 0 and height > 0:
            x_center = (block.bbox[0] + block.bbox[2]) / (2 * width)
            y_center = (block.bbox[1] + block.bbox[3]) / (2 * height)
            text_occurrences[(band, val)].append((block.page_index, x_center, y_center))
        parsed = _number_value(raw)
        if parsed is not None:
            numbered[band].append((block.page_index, parsed[0], positions(block), parsed[1]))
            vertical_positions[(band, block.page_index, parsed[0], parsed[1])].append(
                ((block.bbox[1] + block.bbox[3]) / 2) / height
            )
        elif embedded_folio is not None and running_title:
            # The folio inside a running head still sequences its neighbours;
            # its position is the title's, so alignment is not compared.
            embedded = _number_value(embedded_folio)
            if embedded is not None:
                numbered[band].append((block.page_index, embedded[0], None, embedded[1]))
    # More than one standalone numeral in a single margin band on a page
    # is ambiguous (often a numbered list or page-local references), not
    # reliable evidence of one running folio. Do not use those numerals to
    # corroborate a sequence on adjacent pages either.
    numeric_counts: dict[tuple[str, int], int] = defaultdict(int)
    for block in blocks:
        if block.bbox is None or not _valid_bbox(block.bbox) or not valid_page(block.page_index):
            continue
        height = sizes[block.page_index][1]
        band = (
            "header"
            if block.bbox[3] < 0.12 * height
            else "footer"
            if block.bbox[1] > 0.88 * height
            else None
        )
        if band and _number_value(block.text.strip()) is not None:
            numeric_counts[(band, block.page_index)] += 1
    preferred_numeric: dict[tuple[str, int], set[tuple[int, str]]] = defaultdict(set)
    ambiguous_numeric_bands: set[tuple[str, int]] = set()
    for band_page, count in numeric_counts.items():
        if count < 2:
            continue
        page = band_page[1]
        numerals = [
            (block, _number_value(block.text.strip()))
            for block, block_band in candidates.values()
            if block_band == band_page[0]
            and block.page_index == page
            and _number_value(block.text.strip()) is not None
            and block.bbox is not None
        ]
        ranked = sorted(
            (
                min(block.bbox[1], sizes[page][1] - block.bbox[3]),
                parsed,
            )
            for block, parsed in numerals
            if parsed is not None and block.bbox is not None
        )
        if ranked and (len(ranked) == 1 or ranked[0][0] < ranked[1][0]):
            preferred_numeric[band_page].add(ranked[0][1])
        else:
            ambiguous_numeric_bands.add(band_page)
    if ambiguous_numeric_bands and warnings is not None:
        warnings.append(
            "Equally positioned margin numerals retained; verify page-number candidates"
        )
    if ambiguous_numeric_bands and review_reasons is not None:
        review_reasons.add("ambiguous_page_numbers")
    sequential_pages: dict[str, set[int]] = defaultdict(set)
    qualifying_sequences: dict[tuple[str, int, str], set[int]] = defaultdict(set)
    for band, entries in numbered.items():
        entries = [
            entry
            for entry in entries
            if (band, entry[0]) not in ambiguous_numeric_bands
            and (
                (band, entry[0]) not in preferred_numeric
                or (entry[1], entry[3]) in preferred_numeric[(band, entry[0])]
            )
        ]
        by_key: dict[tuple[int, int, str], list[tuple[float, float] | None]] = defaultdict(list)
        for page, folio_number, position, notation in entries:
            by_key[(page, folio_number, notation)].append(position)
        for page, folio_number, position, notation in entries:
            successors = by_key.get((page + 1, folio_number + 1, notation), [])
            for next_position in successors:
                if not _aligned_folios(position, next_position):
                    continue
                current_y = vertical_positions.get((band, page, folio_number, notation), [])
                next_y = vertical_positions.get((band, page + 1, folio_number + 1, notation), [])
                if (
                    current_y
                    and next_y
                    and not any(
                        abs(first_y - second_y) <= 0.025
                        for first_y in current_y
                        for second_y in next_y
                    )
                ):
                    continue
                if notation == "arabic":
                    sequential_pages[band].update((page, page + 1))
                    qualifying_sequences[(band, folio_number - page, notation)].update(
                        (page, page + 1)
                    )
                else:
                    # Two-page Roman sequences may be section markers.
                    final_positions = by_key.get((page + 2, folio_number + 2, notation), [])
                    if any(_aligned_folios(next_position, final) for final in final_positions):
                        sequential_pages[band].update((page, page + 1, page + 2))
                        if page_label_matches(page + 2, folio_number + 2, notation):
                            qualifying_sequences[(band, folio_number - page, notation)].update(
                                (page, page + 1, page + 2)
                            )
    series_at_page: dict[int, set[tuple[str, int, str]]] = defaultdict(set)
    for series, pages in qualifying_sequences.items():
        for page in pages:
            series_at_page[page].add(series)
    selected_sequences: dict[int, set[tuple[str, int, str]]] = defaultdict(set)
    ambiguous_sequence_pages: set[int] = set()
    for page, series_set in series_at_page.items():
        if len(series_set) == 1:
            selected_sequences[page].update(series_set)
            continue
        ranked_series = []
        for series in series_set:
            band, offset, notation = series
            distances = []
            for block, block_band in candidates.values():
                parsed = _number_value(block.text.strip())
                if (
                    block_band == band
                    and block.page_index == page
                    and parsed == (page + offset, notation)
                    and block.bbox is not None
                ):
                    distances.append(min(block.bbox[1], sizes[page][1] - block.bbox[3]))
            if distances:
                ranked_series.append(
                    (
                        0 if page_label_matches(page, page + offset, notation) else 1,
                        min(distances),
                        series,
                    )
                )
        ranked_series.sort(key=lambda item: (item[0], item[1]))
        if ranked_series and (
            len(ranked_series) == 1 or ranked_series[0][:2] < ranked_series[1][:2]
        ):
            selected_sequences[page].add(ranked_series[0][2])
        else:
            ambiguous_sequence_pages.add(page)
    if ambiguous_sequence_pages and warnings is not None:
        warnings.append("Multiple page-number sequences retained; verify pagination")
    if ambiguous_sequence_pages and review_reasons is not None:
        review_reasons.add("ambiguous_page_numbers")
    if (
        page_labels is not None
        and any(
            not page_label_matches(page, number, notation)
            for (_band, offset, notation), pages in qualifying_sequences.items()
            for page in pages
            for number in (page + offset,)
        )
        and warnings is not None
    ):
        warnings.append("Printed page numbers disagree with PDF page labels")
    edits = []
    for block, band in candidates.values():
        bbox = block.bbox
        if bbox is None:
            continue
        value, embedded_folio = _running_parts(block.text)
        is_number = _number_value(block.text.strip()) is not None
        confirmed_number = (
            is_number
            and (band, block.page_index) not in ambiguous_numeric_bands
            and block.page_index not in ambiguous_sequence_pages
            and block.page_index in sequential_pages[band]
            and (
                not series_at_page.get(block.page_index)
                or (
                    band,
                    (_number_value(block.text.strip()) or (0, ""))[0] - block.page_index,
                    (_number_value(block.text.strip()) or (0, ""))[1],
                )
                in selected_sequences[block.page_index]
            )
        )
        # Repetition alone is insufficient: separate margin prose may recur
        # at unrelated horizontal or vertical positions on different pages.
        width, height = sizes[block.page_index]
        repeated = False
        if width > 0 and height > 0:
            x_center = (bbox[0] + bbox[2]) / (2 * width)
            y_center = (bbox[1] + bbox[3]) / (2 * height)
            repeated = any(
                page != block.page_index
                and _aligned_number_positions(x_center, other_x)
                and abs(y_center - other_y) <= 0.025
                for page, other_x, other_y in text_occurrences[(band, value)]
            )
        if is_number and confirmed_number and settings.remove_page_numbers:
            reason = "sequential/repeated page number"
        elif (
            not PAGE_NUMBER.fullmatch(block.text.strip())
            and _titled(value)
            and (
                len(block.text.split()) >= 2
                or (block.kind == "heading" and (band, value) in running_titles)
            )
            and repeated
            and (block.kind != "heading" or (band, value) in running_titles)
            and (
                (band == "header" and settings.remove_headers)
                or (band == "footer" and settings.remove_footers)
            )
        ):
            reason = "repeated running " + band
            if embedded_folio is not None:
                reason += " with page number"
        else:
            continue
        edits.append(
            CleanupEdit(
                block_id=block.id,
                original=block.text,
                replacement="",
                reason=reason,
                confidence=0.98,
                accepted=True,
            )
        )
    return edits


def _space_above(blocks: list[DocumentBlock], index: int, omitted: set[str]) -> str | None:
    """Describe the whitespace separating a line from the text above it.

    Returns "page" when it is the first retained line of its page, "gap"
    when at least half its own line height of space precedes it, "tight"
    when it is packed against the line above, and None without geometry.
    """
    block = blocks[index]
    previous = next(
        (blocks[j] for j in range(index - 1, -1, -1) if blocks[j].id not in omitted), None
    )
    if previous is None or previous.page_index != block.page_index:
        return "page"
    if not block.bbox or not previous.bbox:
        return None
    if not _valid_bbox(block.bbox) or not _valid_bbox(previous.bbox):
        return None
    height = block.bbox[3] - block.bbox[1]
    return "gap" if block.bbox[1] - previous.bbox[3] >= 0.5 * height else "tight"


def propose_chapters(
    blocks: list[DocumentBlock],
    omitted: set[str],
    toc: list[list],
    settings: ChapterSettings,
    extra_heading_ids: set[str] | None = None,
) -> ChapterProposal:
    """Segment by marked or formatted headings; require review if insufficient evidence."""
    warnings: list[str] = []
    heading_indices = []
    # Typography is supporting evidence for unlabeled prose headings. Require
    # substantial size contrast with the body and reject sentence-like prose.
    body_sizes = sorted(
        float(block.font_size)
        for block in blocks
        if block.id not in omitted
        and block.font_size is not None
        and 5 <= float(block.font_size) <= 40
    )
    typical_size = body_sizes[(len(body_sizes) - 1) // 2] if len(body_sizes) >= 3 else None
    contents_lines, contents_titles = _printed_contents(blocks, omitted, typical_size)
    typography_ids: set[int] = set()
    roman_sequence = roman_sequence_heading_indices(
        blocks, {j for j, item in enumerate(blocks) if item.id in omitted} | set(contents_lines)
    )
    for i, block in enumerate(blocks):
        if block.id in omitted or i in contents_lines:
            # Entries on a printed contents page are references, not headings.
            continue
        text = block.text.strip()
        is_typographic_heading = (
            typical_size is not None
            and block.font_size is not None
            and math.isfinite(float(block.font_size))
            and float(block.font_size) >= max(typical_size * 1.35, typical_size + 3)
            and 1 <= len(text.split()) <= 9
            and len(text) <= 90
            and not text.endswith((".", "?", "!", ",", ";", ":"))
            # A hyphenated line break or lowercase start marks a wrapped
            # large-font line (e.g. catalogue entries), not a heading.
            and not WRAPPED_LINE_END.search(text)
            and not text[:1].islower()
            and not text.isdecimal()
            and not PAGE_REFERENCE_END.search(text)
            and (_wordlike(text) or text in {"I", "V", "X"})
            # A display line packed against the text above it (advert copy,
            # a drop-cap line) does not open a chapter; whitespace or a new
            # page does.
            and _space_above(blocks, i, omitted) != "tight"
            and block.kind not in {"table", "footnote", "caption", "equation", "list"}
        )
        if is_typographic_heading:
            typography_ids.add(i)
        if (
            is_heading_line(text)
            or i in roman_sequence
            or block.id in (extra_heading_ids or set())
            or is_typographic_heading
            or i in contents_titles
        ):
            heading_indices.append(i)
    # A lone "I"/"V"/"X" is a chapter numeral only beside longer numerals
    # such as "II"; in scans it is usually an OCR'd column rule.
    if not any(
        len(blocks[i].text.strip()) >= 2 and ROMAN.fullmatch(blocks[i].text.strip())
        for i in typography_ids
    ):
        lone = {i for i in typography_ids if not _wordlike(blocks[i].text.strip())}
        typography_ids -= lone
        heading_indices = [
            i
            for i in heading_indices
            if i not in lone or is_heading_line(blocks[i].text) or i in contents_titles
        ]
    # Combine confirmed bookmark anchors with textual headings. Some books mix
    # numbered headings and ornamental titles; do not discard the TOC merely
    # because a subset of chapters matched the regular expression.
    bookmark_titles: dict[int, str] = {}
    malformed_bookmarks = 0
    valid_bookmarks: list[tuple[str, int]] = []
    for entry in toc:
        # Bookmarks are advisory metadata. Corrupt/third-party TOC records
        # must not abort an otherwise usable source-text chapter analysis.
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            malformed_bookmarks += 1
            continue
        depth, title, page_num = entry[:3]
        if (
            isinstance(depth, bool)
            or not isinstance(depth, int)
            or isinstance(page_num, bool)
            or not isinstance(page_num, int)
            or depth < 1
            or page_num < 1
            or not isinstance(title, str)
        ):
            malformed_bookmarks += 1
            continue
        if depth > 2:
            continue
        valid_bookmarks.append((title, page_num))

    # A printed TOC can be offset from physical PDF pages by front matter.
    # Infer a nontrivial offset only from at least two distinct, uniquely
    # matched textual headings and no conflicting unique heading evidence.
    offset_evidence: dict[int, set[str]] = defaultdict(set)
    for title, page_num in valid_bookmarks:
        normalized = _title_key(title)
        matches = [
            i
            for i in heading_indices
            if blocks[i].id not in omitted and _title_key(blocks[i].text) == normalized
        ]
        if len(matches) == 1:
            offset = blocks[matches[0]].page_index - (page_num - 1)
            if abs(offset) <= 128:
                offset_evidence[offset].add(normalized)
    inferred_offset: int | None = None
    if len(offset_evidence) == 1:
        offset, titles = next(iter(offset_evidence.items()))
        if abs(offset) > 2 and len(titles) >= 2:
            inferred_offset = offset
            warnings.append(
                f"PDF bookmark page offset {offset:+d} inferred from "
                f"{len(titles)} unique headings; verify chapter alignment"
            )

    for title, page_num in valid_bookmarks:
        page_index = page_num - 1
        title_normalized = _title_key(title)
        if not title_normalized:
            continue
        matching = [
            i
            for i, block in enumerate(blocks)
            if block.id not in omitted and _title_key(block.text) == title_normalized
        ]
        exact = [i for i in matching if blocks[i].page_index == page_index]
        # A TOC page number may refer to printed rather than physical pages.
        # Correct only a unique nearby title, never a duplicated phrase.
        nearby = [i for i in matching if abs(blocks[i].page_index - page_index) <= 2]
        match = (
            exact[0] if len(exact) == 1 else (nearby[0] if not exact and len(nearby) == 1 else None)
        )
        if match is None and not exact and not nearby and inferred_offset is not None:
            shifted = [i for i in matching if blocks[i].page_index == page_index + inferred_offset]
            if len(shifted) == 1:
                match = shifted[0]
        if match is not None:
            heading_indices.append(match)
            bookmark_titles[match] = title.strip()
            if blocks[match].page_index != page_index:
                warnings.append(
                    f"TOC entry {title!r} points to PDF page {page_num}; "
                    f"matched unique title on page {blocks[match].page_index + 1}"
                )
    if malformed_bookmarks:
        warnings.append(
            f"Skipped {malformed_bookmarks} malformed PDF bookmark "
            "record(s); verify chapter boundaries manually"
        )
    # Large type crowding one page (a contents listing, an advert, a scanned
    # cover read as text) is layout, not a run of chapter openings.
    per_page: dict[int, list[int]] = defaultdict(list)
    for i in typography_ids:
        per_page[blocks[i].page_index].append(i)
    crowded = {i for ids in per_page.values() if len(ids) >= 4 for i in ids}
    if crowded:
        typography_ids -= crowded
        heading_indices = [
            i
            for i in heading_indices
            if i not in crowded or is_heading_line(blocks[i].text) or i in contents_titles
        ]
    # A chapter label on a contents-style page (most lines end in a page
    # reference) is a listing when the same label opens a chapter later.
    lines_on_page: dict[int, list[str]] = defaultdict(list)
    for block in blocks:
        if block.id not in omitted and block.text.strip():
            lines_on_page[block.page_index].append(block.text.strip())
    listing_pages = {
        page
        for page, texts in lines_on_page.items()
        if len(texts) >= 6
        and sum(
            bool(PAGE_REFERENCE_END.search(text) or re.fullmatch(r"\d{1,4}", text))
            for text in texts
        )
        >= 0.3 * len(texts)
    }
    # A contents run spans consecutive pages; fill single-page gaps.
    listing_pages |= {
        page + 1
        for page in listing_pages
        if page + 2 in listing_pages and page + 1 in lines_on_page
    }
    label_positions: dict[str, list[int]] = defaultdict(list)
    for i in heading_indices:
        if NUMBERED_LABEL.match(blocks[i].text.strip()):
            label_positions[_label_key(blocks[i].text)].append(i)
    listed = {
        i
        for positions in label_positions.values()
        for i in positions[:-1]
        if blocks[i].page_index in listing_pages and i not in bookmark_titles
    }
    heading_indices = [i for i in heading_indices if i not in listed]
    numbered_labels = sum(
        1 for i in heading_indices if NUMBERED_LABEL.match(blocks[i].text.strip())
    )
    # Candidates supported only by font size or by LLM classification.
    llm_ids = extra_heading_ids or set()
    weak = {
        i
        for i in heading_indices
        if (i in typography_ids or blocks[i].id in llm_ids)
        and i not in bookmark_titles
        and i not in contents_titles
        and not is_heading_line(blocks[i].text)
    }
    llm_only = {i for i in weak if i not in typography_ids}
    if len(bookmark_titles) >= 2 or contents_titles or numbered_labels >= 3:
        # A PDF outline or printed contents that matches the text is stronger
        # evidence than font size or LLM classification. Do not let material
        # it omits (catalogue entries, scene breaks, stray running heads)
        # split the book into spurious chapters.
        if weak:
            heading_indices = [i for i in heading_indices if i not in weak]
            if weak - llm_only:
                warnings.append(
                    f"Ignored {len(weak - llm_only)} font-size-only heading candidate(s) "
                    "not in the PDF outline, printed contents or numbered chapter labels; "
                    "verify chapter boundaries"
                )
            if llm_only:
                warnings.append(
                    f"Ignored {len(llm_only)} LLM-proposed heading(s) not in the PDF "
                    "outline, printed contents or numbered chapter labels; "
                    "verify chapter boundaries"
                )
    # A contents entry naming the line right after another heading is that
    # chapter's subtitle ("CHAPTER III." / "ON RELATIVE GROWINGS."), not a
    # new boundary.
    detected = set(heading_indices)
    subtitles = set()
    for i in contents_titles:
        previous = next((j for j in range(i - 1, -1, -1) if blocks[j].id not in omitted), None)
        if previous in detected and previous not in contents_titles:
            subtitles.add(i)
    heading_indices = [i for i in heading_indices if i not in subtitles]
    heading_indices = sorted(set(heading_indices))
    if not blocks:
        raise ExtractionError("No text found in PDF; no chapters can be created")
    if not heading_indices and not settings.allow_single_chapter:
        raise ExtractionError(
            "No reliable chapter boundaries found. Edit a manifest or retry "
            "with --allow-single-chapter; no text was silently grouped."
        )
    # Removed pagination noise above the first heading (e.g. a running header)
    # is not front matter. Fold it into the first chapter rather than creating
    # an empty, low-confidence chapter that blocks synthesis.
    noise_prefix = (
        bool(heading_indices)
        and heading_indices[0] != 0
        and all(block.id in omitted for block in blocks[: heading_indices[0]])
    )
    starts = ([0] if 0 not in heading_indices and not noise_prefix else []) + heading_indices
    if not heading_indices:
        warnings.append("Single-chapter mode explicitly requested")
    elif starts[0] == 0 and heading_indices[0] != 0:
        warnings.append("Pre-chapter material retained in its own front-matter chapter")
    chapters = []
    for number, start in enumerate(starts, 1):
        end = starts[number] if number < len(starts) else len(blocks)
        if start == 0 and heading_indices and start != heading_indices[0]:
            name = "Front Matter"
            confidence = 0.7
            evidence = ["unassigned material before chapter heading"]
        elif start in heading_indices:
            name = bookmark_titles.get(start) or contents_titles.get(
                start, blocks[start].text.strip()
            )
            confidence = (
                0.95
                if start in bookmark_titles
                and not any(
                    f"TOC entry {bookmark_titles[start]!r} points" in warning
                    for warning in warnings
                )
                else 0.85
                if start in bookmark_titles
                else 0.9
                if start in contents_titles
                else 0.82
                if start in typography_ids
                else 0.8
                if start in llm_only
                else 0.9
            )
            evidence = (
                ["PDF bookmark/TOC matched unique source title"]
                if start in bookmark_titles
                else ["printed contents entry matched unique later heading"]
                if start in contents_titles
                else ["typographic size contrast with body text"]
                if start in typography_ids
                else ["LLM structure classification (advisory)"]
                if start in llm_only
                else ["explicit heading text"]
            )
            space = _space_above(blocks, start, omitted)
            if space == "page":
                evidence = [*evidence, "opens a new page"]
            elif space == "gap":
                evidence = [*evidence, "vertical whitespace above"]
        else:
            name = "Full Book"
            confidence = 0.5
            evidence = ["explicit single chapter override"]
        chapter = Chapter(
            id=f"c{number:04d}",
            number=number,
            title=name,
            start_block=0 if number == 1 else start,
            end_block=end,
            confidence=confidence,
            evidence=evidence,
        )
        if confidence < 0.85:
            chapter.warnings.append("Chapter boundary has low confidence; verify manually")
        chapter.generated_fingerprint = generated_chapter_fingerprint(chapter)
        chapter.generated_title = chapter.title
        chapter.generated_start_block = chapter.start_block
        chapter.generated_end_block = chapter.end_block
        chapter.generated_voice_id = chapter.voice_id
        chapters.append(chapter)
    empty_chapter = any(
        not chapter_has_speakable_text(
            blocks, chapter.start_block, chapter.end_block, {block_id: "" for block_id in omitted}
        )
        for chapter in chapters
    )
    return ChapterProposal(
        chapters=chapters,
        warnings=warnings,
        review_reasons={"empty_chapter"} if empty_chapter else set(),
    )


def validate_chapter_coverage(blocks: list[DocumentBlock], chapters: list[Chapter]) -> None:
    """Chapter boundaries are ordered, contiguous, nonempty, and cover every source block."""
    if not chapters:
        raise ExtractionError("Manifest does not contain any chapters")
    expected = 0
    for ordinal, chapter in enumerate(chapters, 1):
        if chapter.number != ordinal:
            raise ExtractionError("Manifest chapter numbers must be consecutive and 1-based")
        if chapter.start_block != expected:
            raise ExtractionError(
                f"Manifest chapter {ordinal} overlaps or leaves an uncovered block range"
            )
        if chapter.end_block > len(blocks):
            raise ExtractionError("Manifest chapter extends beyond source blocks")
        expected = chapter.end_block
    if expected != len(blocks):
        raise ExtractionError("Manifest does not cover all original source blocks")


def chapter_has_speakable_text(
    blocks: list[DocumentBlock],
    start: int,
    end: int,
    replacements: dict[str, str] | None = None,
) -> bool:
    """Use one cleanup-aware narration rule for coverage and conversion gates."""
    from pdf2audiobook.audio import has_speakable_narration

    replacement_map = replacements or {}
    return any(
        has_speakable_narration(replacement_map.get(block.id, block.text))
        for block in blocks[start:end]
    )


def chapter_coverage_report(manifest: BookManifest) -> dict[str, object]:
    """Validate provenance, cleanup anchors and exact-once block coverage."""
    validate_chapter_coverage(manifest.blocks, manifest.chapters)
    ids = [block.id for block in manifest.blocks]
    if len(ids) != len(set(ids)):
        raise ExtractionError("Duplicate source block IDs in manifest")
    span_ids = [span.id for span in manifest.spans]
    if len(span_ids) != len(set(span_ids)):
        raise ExtractionError("Duplicate source span IDs in manifest")
    known_spans = set(span_ids)
    assigned_spans: set[str] = set()
    for block in manifest.blocks:
        if known_spans and not block.span_ids:
            raise ExtractionError("Source block has no source span provenance")
        for span_id in block.span_ids:
            if span_id not in known_spans:
                raise ExtractionError("Source block references missing source spans")
            if span_id in assigned_spans:
                raise ExtractionError("Source span is assigned more than once")
            assigned_spans.add(span_id)
    if assigned_spans != known_spans:
        raise ExtractionError("Manifest contains unassigned source spans")
    by_id = {block.id: block for block in manifest.blocks}
    accepted: dict[str, str] = {}
    for edit in manifest.edits:
        if edit.block_id not in by_id:
            raise ExtractionError("Cleanup edit references missing source block")
        if edit.original != by_id[edit.block_id].text:
            raise ExtractionError("Cleanup edit original does not match source block")
        if edit.accepted:
            if edit.block_id in accepted:
                raise ExtractionError("Multiple accepted edits for source block")
            accepted[edit.block_id] = edit.replacement
    empty_chapters = [
        chapter.number
        for chapter in manifest.chapters
        if not chapter_has_speakable_text(
            manifest.blocks, chapter.start_block, chapter.end_block, accepted
        )
    ]
    return {
        "valid": True,
        "source_blocks": len(ids),
        "source_spans": len(span_ids),
        "covered_blocks": sum(ch.end_block - ch.start_block for ch in manifest.chapters),
        "uncovered_blocks": 0,
        "duplicate_blocks": 0,
        "accepted_cleanup_blocks": len(accepted),
        "narrated_blocks": sum(
            1 for block in manifest.blocks if chapter_has_speakable_text([block], 0, 1, accepted)
        ),
        "chapters": len(manifest.chapters),
        "empty_chapters": empty_chapters,
    }


NOTE_MARKER = re.compile(r"^\s*(?P<marker>\d{1,3}|[*†‡§])")


def _anchor_pattern(marker: str) -> re.Pattern[str]:
    """A note anchor glued to a word or its punctuation: "world.5", "secrecy,26"."""
    return re.compile(rf"(?P<lead>[^\W\d_][.,;:!?\"'”’)\]]?){re.escape(marker)}(?!\d)")


def _unique_anchor(
    head: DocumentBlock, body: list[DocumentBlock], position: dict[str, int]
) -> int | None:
    """Index in body of the one line before the note, on its page, holding its anchor."""
    match = NOTE_MARKER.match(head.text)
    if match is None:
        return None
    anchor = _anchor_pattern(match.group("marker"))
    candidates = [
        index
        for index, block in enumerate(body)
        if block.page_index == head.page_index
        and position[block.id] < position[head.id]
        and len(anchor.findall(block.text)) == 1
    ]
    others = [
        block
        for block in body
        if block.page_index == head.page_index
        and position[block.id] < position[head.id]
        and anchor.search(block.text)
    ]
    return candidates[0] if len(candidates) == 1 and len(others) == 1 else None


def footnote_anchor_edits(blocks: list[DocumentBlock], edited: set[str]) -> list[CleanupEdit]:
    """Audited removal of note-anchor digits from narration ("world.5" -> "world.").

    Only an anchor that uniquely matches a classified note on its page is
    removed, only the marker characters are deleted, and blocks that already
    carry an accepted edit are left alone. Source blocks are never changed.
    """
    position = {block.id: index for index, block in enumerate(blocks)}
    body = [block for block in blocks if block.kind != "footnote"]
    markers: dict[int, list[str]] = defaultdict(list)
    for block in blocks:
        if block.kind != "footnote":
            continue
        index = _unique_anchor(block, body, position)
        if index is not None and body[index].id not in edited:
            match = NOTE_MARKER.match(block.text)
            assert match is not None
            markers[index].append(match.group("marker"))
    edits = []
    for index, found in sorted(markers.items()):
        original = body[index].text
        replacement = original
        for marker in found:
            replacement = _anchor_pattern(marker).sub(r"\g<lead>", replacement, count=1)
        if replacement != original:
            edits.append(
                CleanupEdit(
                    block_id=body[index].id,
                    original=original,
                    replacement=replacement,
                    reason="footnote anchor marker " + ", ".join(found) + " (note handled)",
                    confidence=0.9,
                    accepted=True,
                )
            )
    return edits


def footnote_omit_edits(blocks: list[DocumentBlock]) -> list[CleanupEdit]:
    """Create audited exclusions for blocks classified as footnotes."""
    return [
        CleanupEdit(
            block_id=block.id,
            original=block.text,
            replacement="",
            reason="explicit footnotes=omit policy (conservative classification)",
            confidence=0.9,
            accepted=True,
        )
        for block in blocks
        if block.kind == "footnote"
    ]


def place_footnotes(
    blocks: list[DocumentBlock], policy: str
) -> tuple[list[DocumentBlock], int, int]:
    """Reorder a chapter's classified footnotes for narration; never drop any.

    "end" moves every note after the chapter body. "inline" moves a note to
    the end of the paragraph holding its anchor ("world.5" for note "5 ...")
    when exactly one such anchor precedes it on the same page; otherwise the
    note keeps its PDF position. Other policies keep PDF order. Returns the
    narration order and the counts of relocated and kept-in-place notes
    (a note is its marker line plus continuation lines).
    """
    notes = [block for block in blocks if block.kind == "footnote"]
    # Group each numbered note with its unnumbered continuation lines; lines
    # before the first marker continue a note from the previous page.
    items: list[list[DocumentBlock]] = []
    for block in notes:
        if (
            NOTE_MARKER.match(block.text)
            or not items
            or items[-1][0].page_index != block.page_index
        ):
            items.append([block])
        else:
            items[-1].append(block)
    if policy not in {"inline", "end"} or not notes:
        return blocks, 0, len(items)
    body = [block for block in blocks if block.kind != "footnote"]
    if policy == "end":
        return body + notes, len(items), 0
    position = {block.id: index for index, block in enumerate(blocks)}
    after: dict[int, list[DocumentBlock]] = defaultdict(list)  # body index -> notes
    relocated = kept = 0
    for item in items:
        head = item[0]
        anchor_index = _unique_anchor(head, body, position)
        if anchor_index is not None:
            while anchor_index + 1 < len(body) and _is_wrapped_line(
                body[anchor_index],
                body[anchor_index + 1],
                body[anchor_index + 2] if anchor_index + 2 < len(body) else None,
            ):
                anchor_index += 1
            relocated += 1
        else:
            # Keep the PDF position: after the last body line that preceded it.
            anchor_index = max(
                (i for i, block in enumerate(body) if position[block.id] < position[head.id]),
                default=-1,
            )
            kept += 1
        after[anchor_index].extend(item)
    ordered = list(after.get(-1, []))
    for index, block in enumerate(body):
        ordered.append(block)
        ordered.extend(after.get(index, []))
    if sorted(position[block.id] for block in ordered) != list(range(len(blocks))):
        raise ExtractionError("Footnote placement must keep every source block exactly once")
    return ordered, relocated, kept


def render_chapter_narration(
    manifest: BookManifest, chapter: Chapter, footnotes: str = "warn"
) -> str:
    """Narration text of one chapter, rendered in memory from the current manifest."""
    replacements = {edit.block_id: edit.replacement for edit in manifest.edits if edit.accepted}
    chapter_blocks, _, _ = place_footnotes(
        manifest.blocks[chapter.start_block : chapter.end_block], footnotes
    )
    return reflow_narration_lines(
        chapter_blocks,
        replacements,
        supporting_text=" ".join(block.text for block in manifest.blocks),
    )


def render_chapter_texts(manifest: BookManifest, folder: Path, footnotes: str = "warn") -> None:
    """Regenerate derived text from source-linked, verified edits and manual boundaries."""
    from pdf2audiobook.workspace import atomic_write, digest_bytes, digest_file, write_json

    report = chapter_coverage_report(manifest)
    for chapter in manifest.chapters:
        content = render_chapter_narration(manifest, chapter, footnotes).encode("utf-8")
        path = folder / "chapters" / f"{chapter.number:03d}.txt"
        # Compare existing chapter text using bounded reads. read_bytes()
        # would duplicate an entire long chapter in memory on every resume.
        if not path.is_file() or digest_file(path) != digest_bytes(content):
            atomic_write(path, content)
    # A re-plan with fewer chapters must not leave stale derived text behind.
    # Only remove files named like derived chapter text; others are untouched.
    current = {f"{chapter.number:03d}.txt" for chapter in manifest.chapters}
    for stale in (folder / "chapters").glob("[0-9][0-9][0-9]*.txt"):
        if CHAPTER_TEXT_NAME.fullmatch(stale.name) and stale.name not in current:
            stale.unlink(missing_ok=True)
    write_json(folder / "coverage.json", report)


def _is_wrapped_line(
    before: DocumentBlock, after: DocumentBlock, after_next: DocumentBlock | None = None
) -> bool:
    """Join nearby consecutive body lines only when geometry supports a soft wrap."""
    if before.kind in {"heading", "table", "footnote", "caption", "equation"}:
        return False
    if after.kind in {"heading", "list", "table", "footnote", "caption", "equation"}:
        return False
    if not before.text.strip() or not after.text.strip():
        return False
    if after.page_index == before.page_index + 1:
        # A sentence running over a page break: no closing punctuation before
        # the break and a lowercase continuation after it (removed running
        # heads and folios between them are already skipped).
        return (
            not before.text.rstrip().endswith((".", "?", "!", ":", ";", '"', "”", "’", ")", "]"))
            and after.text.lstrip()[:1].islower()
        )
    if before.page_index != after.page_index or not before.bbox or not after.bbox:
        return False
    if not _valid_bbox(before.bbox) or not _valid_bbox(after.bbox):
        return False
    next_text = after.text.lstrip()
    markers = ("“", '"', "‘", "'", "—", "–", "•", "*", "§", "#")
    if next_text.startswith(markers) or before.text.strip().startswith(("*", "§", "#")):
        return False
    if before.text.rstrip().endswith(":") and (
        is_list_line(next_text) or re.match(r"^[-–—]\s+", next_text)
    ):
        return False
    # An initial before a name ("J. Smith") and a year before ")" ("1990) was")
    # are prose, which is_list_line already knows; real markers start a new line.
    if is_list_line(
        next_text,
        previous_text=before.text,
        next_text=after_next.text if after_next is not None else None,
    ) or re.match(r"^-\s+", next_text):
        return False
    if next_text.isupper() and len(next_text.split()) <= 8:
        return False
    line_height = max(1.0, before.bbox[3] - before.bbox[1])
    vertical_gap = after.bbox[1] - before.bbox[3]
    left_shift = after.bbox[0] - before.bbox[0]
    if before.kind == "list":
        # A list ends at a font change or at a line outdented from its items;
        # wrapped continuation lines stay at or inside the item's left edge.
        if (
            before.font_size is not None
            and after.font_size is not None
            and abs(float(before.font_size) - float(after.font_size)) > 0.5
        ):
            return False
        if left_shift < -2:
            return False
        # A sentence-final list item followed at the marker margin is followed
        # by a new body paragraph. A hanging continuation can remain flush-left
        # when the list item itself has no sentence-ending punctuation.
        if left_shift <= 2 and before.text.rstrip().endswith((".", "?", "!", ":", ";")):
            return False
    # Preserve indented paragraphs, section breaks and column transitions.
    return -2 <= vertical_gap <= 0.8 * line_height and abs(left_shift) <= max(12.0, line_height)


def reflow_narration_lines(
    blocks: list[DocumentBlock],
    replacements: dict[str, str] | None = None,
    *,
    supporting_text: str | None = None,
) -> str:
    """Preserve headings and breaks while joining clear PDF soft-wrapped body lines.

    No source blocks are mutated. A line-end hyphen is removed only when the
    joined word appears elsewhere without a hyphen in the source document.
    """
    replacements = replacements or {}
    corpus = supporting_text if supporting_text is not None else " ".join(b.text for b in blocks)
    corpus_words = {word.casefold() for word in re.findall(r"[^\W\d_]+", corpus)}
    paragraphs: list[str] = []
    current = ""
    previous: DocumentBlock | None = None
    for block_index, block in enumerate(blocks):
        text = replacements.get(block.id, block.text).strip()
        if not text:
            # An excluded running header/footer should not force a new paragraph.
            if not block.text.strip():
                if current:
                    paragraphs.append(current)
                    current = ""
                previous = None
            continue
        after_next = blocks[block_index + 1] if block_index + 1 < len(blocks) else None
        if current and previous is not None and _is_wrapped_line(previous, block, after_next):
            if current.endswith("\u00ad"):
                current = current[:-1] + text
            elif current.endswith("-") and text[:1].islower():
                match = re.search(r"([^\W\d_]+)-$", current)
                continuation = re.match(r"([^\W\d_]+)", text)
                if match and continuation:
                    if (match.group(1) + continuation.group(1)).casefold() in corpus_words:
                        current = current[:-1] + text
                    else:
                        current += text
                else:
                    current += " " + text
            else:
                current += " " + text
        else:
            if current:
                paragraphs.append(current)
            current = text
        previous = block
    if current:
        paragraphs.append(current)
    return "\n\n".join(paragraphs).strip() + "\n"
