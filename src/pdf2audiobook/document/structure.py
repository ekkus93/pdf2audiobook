"""Conservative pagination removal and chapter-boundary detection.

Raw blocks are immutable. Cleanup decisions are stored as audited edits.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterator

from pdf2audiobook.config import Chapters as ChapterSettings
from pdf2audiobook.document.coverage import (
    chapter_coverage_report as chapter_coverage_report,
)
from pdf2audiobook.document.coverage import (
    chapter_has_speakable_text as chapter_has_speakable_text,
)
from pdf2audiobook.document.coverage import (
    validate_chapter_coverage as validate_chapter_coverage,
)
from pdf2audiobook.document.listing import is_list_line as is_list_line
from pdf2audiobook.document.narration import (
    footnote_anchor_edits as footnote_anchor_edits,
)
from pdf2audiobook.document.narration import (
    footnote_omit_edits as footnote_omit_edits,
)
from pdf2audiobook.document.narration import (
    place_footnotes as place_footnotes,
)
from pdf2audiobook.document.narration import (
    reflow_narration_lines as reflow_narration_lines,
)
from pdf2audiobook.document.narration import (
    render_chapter_narration as render_chapter_narration,
)
from pdf2audiobook.document.narration import (
    render_chapter_texts as render_chapter_texts,
)
from pdf2audiobook.document.pagination import (
    _AMBIGUOUS_NUMERALS as _AMBIGUOUS_NUMERALS,
)
from pdf2audiobook.document.pagination import (
    _ROMAN_TITLE as _ROMAN_TITLE,
)
from pdf2audiobook.document.pagination import (
    _number_value as _number_value,
)
from pdf2audiobook.document.pagination import (
    _valid_bbox as _valid_bbox,
)
from pdf2audiobook.document.pagination import (
    _wordlike as _wordlike,
)
from pdf2audiobook.document.pagination import (
    pagination_cleanup as pagination_cleanup,
)
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.models import (
    Chapter,
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
PAGE_NUMBER_EDGE_TIE_TOLERANCE_PT = 2.0

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


# A contents entry's leader and page reference: "Chapter One ........ 7" or "… xii".
# A single space before a numeral is not a leader ("Chapter IV" keeps its number).
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
    # Pages that list chapters (a contents run) name chapters; they do not open them.
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
    # Combine confirmed bookmark anchors with textual headings. Some books mix
    # numbered headings and ornamental titles; do not discard the TOC merely
    # because a subset of chapters matched the regular expression.
    bookmark_titles: dict[int, str] = {}
    numeral_anchored: set[int] = set()
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
    headings_by_title: dict[str, list[int]] = defaultdict(list)
    for i in heading_indices:
        if blocks[i].id not in omitted:
            headings_by_title[_title_key(blocks[i].text)].append(i)
    for title, page_num in valid_bookmarks:
        normalized = _title_key(title)
        matches = headings_by_title.get(normalized, [])
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

    # One pass indexes every block by title and every page by its first line, so each
    # outline entry is matched without rescanning the book.
    blocks_by_title: dict[str, list[int]] = defaultdict(list)
    first_on_page: dict[int, int] = {}
    for i, block in enumerate(blocks):
        if block.id in omitted:
            continue
        blocks_by_title[_title_key(block.text)].append(i)
        if block.text.strip():
            first_on_page.setdefault(block.page_index, i)
    for title, page_num in valid_bookmarks:
        page_index = page_num - 1
        title_normalized = _title_key(title)
        if not title_normalized:
            continue
        matching = blocks_by_title.get(title_normalized, [])
        exact = [i for i in matching if blocks[i].page_index == page_index]
        # A TOC page number may refer to printed rather than physical pages.
        # Correct only a unique nearby title, never a duplicated phrase. A page that
        # lists chapters never opens one, so it is not a candidate.
        nearby = [
            i
            for i in matching
            if abs(blocks[i].page_index - page_index) <= 2
            and blocks[i].page_index not in listing_pages
        ]
        match = exact[0] if len(exact) == 1 else None
        wanted = label_number(title)
        if match is None and wanted is not None:
            # Many books open a chapter with only its numeral ("12") while the outline
            # says "Chapter 12". The outline's page is authoritative: take the first
            # line there when it is that chapter's numeral. When the outline uses
            # printed page numbers, the inferred offset locates the physical page.
            candidate_pages = [page_index]
            if inferred_offset is not None:
                candidate_pages.append(page_index + inferred_offset)
            for candidate_page in candidate_pages:
                if candidate_page in listing_pages:
                    continue
                first = first_on_page.get(candidate_page)
                if first is not None and bare_number(blocks[first].text) == wanted:
                    match = first
                    numeral_anchored.add(first)
                    break
        if match is None and not exact and len(nearby) == 1:
            match = nearby[0]
        if match is None and not exact and not nearby and inferred_offset is not None:
            shifted = [
                i
                for i in matching
                if blocks[i].page_index == page_index + inferred_offset
                and blocks[i].page_index not in listing_pages
            ]
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
    # Books often open a chapter with only its numeral. When the printed contents names
    # "Chapter N" and numerals then open pages in order, those numerals are the chapter
    # headings and the contents labels are references to them. Parts and chapters are
    # numbered separately, so labels are keyed by (kind, number).
    numeral_titles: dict[int, str] = {}
    listed_by_kind: dict[str, dict[int, int]] = defaultdict(dict)
    for i, block in enumerate(blocks):
        if block.id in omitted or block.page_index not in listing_pages:
            continue
        key = label_key(block.text)
        if key is not None and NUMBERED_LABEL.match(block.text.strip()):
            listed_by_kind[key[0]].setdefault(key[1], i)
    numeral_kind = "chapter" if listed_by_kind.get("chapter") else "part"
    listed_labels = listed_by_kind.get(numeral_kind, {})
    corroborated: dict[int, int] = {}
    last_number = 0
    for page in sorted(first_on_page):
        i = first_on_page[page]
        if page in listing_pages or i in bookmark_titles:
            continue
        number = bare_number(blocks[i].text)
        if number is not None and number > last_number and number in listed_labels:
            corroborated[i] = number
            last_number = number
    # Running page numbers advance one per page; chapters rarely do. When most
    # consecutive numerals are exactly that far apart, they are page numbers, even if
    # an unnumbered page somewhere shifts the offset.
    steps = sorted((blocks[i].page_index, number) for i, number in corroborated.items())
    pairs = list(zip(steps, steps[1:]))
    lockstep = sum(
        1 for (page_a, num_a), (page_b, num_b) in pairs if page_b - page_a == num_b - num_a
    )
    page_numbers = bool(pairs) and 2 * lockstep >= len(pairs)
    if not page_numbers and len(corroborated) >= 3 and 2 * len(corroborated) >= len(listed_labels):
        for i, number in corroborated.items():
            numeral_titles[i] = contents_label_title(blocks[listed_labels[number]].text)
            if i not in heading_indices:
                heading_indices.append(i)
    anchored_keys = {
        key
        for i, title in bookmark_titles.items()
        if blocks[i].page_index not in listing_pages and (key := label_key(title)) is not None
    } | {(numeral_kind, number) for number in (corroborated.values() if numeral_titles else ())}
    # A chapter label on a contents-style page (most lines end in a page
    # reference) is a listing when the same label opens a chapter later.
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
    # A listed label whose chapter opens elsewhere is a reference to it, not a heading.
    listed |= {
        i
        for i in heading_indices
        if blocks[i].page_index in listing_pages
        and i not in bookmark_titles
        and label_key(blocks[i].text) in anchored_keys
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
        and i not in numeral_titles
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
            name = (
                bookmark_titles.get(start)
                or numeral_titles.get(start)
                or contents_titles.get(start, blocks[start].text.strip())
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
                if start in numeral_titles
                else 0.9
                if start in contents_titles
                else 0.82
                if start in typography_ids
                else 0.8
                if start in llm_only
                else 0.9
            )
            evidence = (
                ["PDF bookmark matched the numbered chapter heading on its page"]
                if start in numeral_anchored
                else ["PDF bookmark/TOC matched unique source title"]
                if start in bookmark_titles
                else ["numeral heading corroborated by the printed contents"]
                if start in numeral_titles
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
