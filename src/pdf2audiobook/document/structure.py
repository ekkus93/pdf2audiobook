"""Conservative pagination removal and chapter-boundary detection.

Raw blocks are immutable. Cleanup decisions are stored as audited edits.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from pdf2audiobook.config import Chapters as ChapterSettings
from pdf2audiobook.config import Pdf as PdfSettings
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.models import BookManifest, Chapter, CleanupEdit, DocumentBlock

HEADING = re.compile(
    r"^(?:(?:chapter|part)\s+(?:\d+|[ivxlcdm]+|one|two|three|four|five|six|"
    r"seven|eight|nine|ten)\b.*|prologue|epilogue|preface|introduction)$",
    re.IGNORECASE,
)
# "Chapter IV regarding ..." is a sentence that cites a chapter, not a label.
ROMAN = re.compile(r"[IVXLCDM]+")
LABEL_PROSE = re.compile(r"^(?i:chapter|part)\s+\S+\s+[a-z]")
CHAPTER_TEXT_NAME = re.compile(r"\d{3,}\.txt")
WRAPPED_LINE_END = re.compile(r"[^\W\d_]-$")
PAGE_NUMBER = re.compile(r"^(?:\d{1,5}|[ivxlcdm]{1,10})$", re.IGNORECASE)

CANONICAL_ROMAN = re.compile(
    r"^M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})"
    r"(?:IX|IV|V?I{0,3})$"
)


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


def labelled_heading(text: str) -> bool:
    """A chapter/part/prologue label line, not prose that cites one."""
    return (
        HEADING.match(text) is not None and len(text.split()) <= 12 and not LABEL_PROSE.match(text)
    )


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


def _aligned_folios(first: tuple[float, float], second: tuple[float, float]) -> bool:
    """Folios align on the paper, or relative to sideways-drifting scanned text."""
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
) -> list[CleanupEdit]:
    """Remove only corroborated pagination patterns confined to margin bands."""
    candidates: dict[str, tuple[DocumentBlock, str]] = {}
    text_occurrences: dict[tuple[str, str], list[tuple[int, float, float]]] = defaultdict(list)
    numbered: dict[str, list[tuple[int, int, tuple[float, float], str]]] = defaultdict(list)
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

    for block in blocks:
        if not block.bbox or not _valid_bbox(block.bbox) or not valid_page(block.page_index):
            continue
        height = sizes[block.page_index][1]
        if block.bbox[1] >= 0.12 * height and block.bbox[3] <= 0.88 * height:
            body_text.add(" ".join(block.text.split()).casefold())
    for block in blocks:
        if not block.bbox or not _valid_bbox(block.bbox) or not valid_page(block.page_index):
            continue
        height = sizes[block.page_index][1]
        top, bottom = block.bbox[1], block.bbox[3]
        band = "header" if bottom < height * 0.12 else ("footer" if top > height * 0.88 else None)
        if not band:
            continue
        # Fail closed when the apparent margin element is continuous with
        # nearby body text; repeated dialogue and list labels are not folios.
        if _adjacent_body_line(block, blocks_by_page[block.page_index], band):
            continue
        val = " ".join(block.text.split()).casefold()
        raw = block.text.strip()
        # Fail closed on standalone quotations, numbered list markers and
        # headings. These can legitimately occur in a page's margin band.
        if block.kind in {"heading", "list", "table", "footnote", "caption", "equation"}:
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
        if val in body_text and not PAGE_NUMBER.fullmatch(raw):
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
        if PAGE_NUMBER.fullmatch(raw):
            if block.font_size is not None and block.font_size > 14:
                continue
            if any(
                other.id != block.id
                and other.bbox is not None
                and _valid_bbox(other.bbox)
                and other.text.strip()
                and other.bbox[0] >= block.bbox[2]
                and 0 <= other.bbox[0] - block.bbox[2] <= sizes[block.page_index][0] * 0.12
                and abs(other.bbox[1] - block.bbox[1]) <= max(5.0, block.bbox[3] - block.bbox[1])
                for other in blocks_by_page[block.page_index]
            ):
                continue
        # A lone numeric line at ordinary body indentation is not sufficient
        # evidence of pagination, even if another page starts with "2".
        if PAGE_NUMBER.fullmatch(raw):
            if not any(
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
    ambiguous_numeric_bands = {key for key, count in numeric_counts.items() if count > 1}
    sequential_pages: dict[str, set[int]] = defaultdict(set)
    for band, entries in numbered.items():
        entries = [entry for entry in entries if (band, entry[0]) not in ambiguous_numeric_bands]
        by_key: dict[tuple[int, int, str], list[tuple[float, float]]] = defaultdict(list)
        for page, folio_number, position, notation in entries:
            by_key[(page, folio_number, notation)].append(position)
        for page, folio_number, position, notation in entries:
            successors = by_key.get((page + 1, folio_number + 1, notation), [])
            for next_position in successors:
                if not _aligned_folios(position, next_position):
                    continue
                if notation == "arabic":
                    sequential_pages[band].update((page, page + 1))
                else:
                    # Two-page Roman sequences may be section markers.
                    final_positions = by_key.get((page + 2, folio_number + 2, notation), [])
                    if any(_aligned_folios(next_position, final) for final in final_positions):
                        sequential_pages[band].update((page, page + 1, page + 2))
    edits = []
    for block, band in candidates.values():
        bbox = block.bbox
        if bbox is None:
            continue
        value = " ".join(block.text.split()).casefold()
        is_number = _number_value(block.text.strip()) is not None
        confirmed_number = (
            is_number
            and (band, block.page_index) not in ambiguous_numeric_bands
            and block.page_index in sequential_pages[band]
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
            and len(block.text.split()) >= 2
            and repeated
            and (
                (band == "header" and settings.remove_headers)
                or (band == "footer" and settings.remove_footers)
            )
        ):
            reason = "repeated running " + band
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


def propose_chapters(
    blocks: list[DocumentBlock],
    omitted: set[str],
    toc: list[list],
    settings: ChapterSettings,
    extra_heading_ids: set[str] | None = None,
) -> tuple[list[Chapter], list[str]]:
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
            and (_wordlike(text) or text in {"I", "V", "X"})
            and block.kind not in {"table", "footnote", "caption", "equation", "list"}
        )
        if is_typographic_heading:
            typography_ids.add(i)
        if (
            labelled_heading(text)
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
            if i not in lone or labelled_heading(blocks[i].text.strip()) or i in contents_titles
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
    # Candidates supported only by font size or by LLM classification.
    llm_ids = extra_heading_ids or set()
    weak = {
        i
        for i in heading_indices
        if (i in typography_ids or blocks[i].id in llm_ids)
        and i not in bookmark_titles
        and i not in contents_titles
        and not labelled_heading(blocks[i].text.strip())
    }
    llm_only = {i for i in weak if i not in typography_ids}
    if len(bookmark_titles) >= 2 or contents_titles:
        # A PDF outline or printed contents that matches the text is stronger
        # evidence than font size or LLM classification. Do not let material
        # it omits (catalogue entries, scene breaks, stray running heads)
        # split the book into spurious chapters.
        if weak:
            heading_indices = [i for i in heading_indices if i not in weak]
            if weak - llm_only:
                warnings.append(
                    f"Ignored {len(weak - llm_only)} font-size-only heading candidate(s) "
                    "not in the PDF outline or printed contents; verify chapter boundaries"
                )
            if llm_only:
                warnings.append(
                    f"Ignored {len(llm_only)} LLM-proposed heading(s) not in the PDF "
                    "outline or printed contents; verify chapter boundaries"
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
        else:
            name = "Full Book"
            confidence = 0.5
            evidence = ["explicit single chapter override"]
        chapters.append(
            Chapter(
                id=f"c{number:04d}",
                number=number,
                title=name,
                start_block=0 if number == 1 else start,
                end_block=end,
                confidence=confidence,
                evidence=evidence,
            )
        )
    return chapters, warnings


def chapter_text(blocks: list[DocumentBlock], chapter: Chapter, omitted: set[str]) -> str:
    """Only audibly retain blocks not removed by accepted audited edits."""
    return (
        "\n".join(
            block.text
            for block in blocks[chapter.start_block : chapter.end_block]
            if block.id not in omitted
        ).strip()
        + "\n"
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


def chapter_coverage_report(manifest: BookManifest) -> dict[str, int | bool]:
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
    return {
        "valid": True,
        "source_blocks": len(ids),
        "source_spans": len(span_ids),
        "covered_blocks": sum(ch.end_block - ch.start_block for ch in manifest.chapters),
        "uncovered_blocks": 0,
        "duplicate_blocks": 0,
        "accepted_cleanup_blocks": len(accepted),
        "narrated_blocks": sum(
            1 for block in manifest.blocks if accepted.get(block.id, block.text).strip()
        ),
        "chapters": len(manifest.chapters),
    }


def render_chapter_texts(manifest: BookManifest, folder: Path) -> None:
    """Regenerate derived text from source-linked, verified edits and manual boundaries."""
    from pdf2audiobook.workspace import atomic_write, digest_bytes, digest_file, write_json

    report = chapter_coverage_report(manifest)
    replacements = {edit.block_id: edit.replacement for edit in manifest.edits if edit.accepted}
    for chapter in manifest.chapters:
        chapter_blocks = manifest.blocks[chapter.start_block : chapter.end_block]
        content = reflow_narration_lines(chapter_blocks, replacements).encode("utf-8")
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


def _is_wrapped_line(before: DocumentBlock, after: DocumentBlock) -> bool:
    """Join nearby consecutive body lines only when geometry supports a soft wrap."""
    if before.kind in {"heading", "list", "table", "footnote", "caption", "equation"}:
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
    if re.match(r"^(?:-\s+|\d+[.)]\s+|[A-Za-z][.)]\s+)", next_text):
        return False
    if next_text.isupper() and len(next_text.split()) <= 8:
        return False
    line_height = max(1.0, before.bbox[3] - before.bbox[1])
    vertical_gap = after.bbox[1] - before.bbox[3]
    left_shift = after.bbox[0] - before.bbox[0]
    # Preserve indented paragraphs, section breaks and column transitions.
    return -2 <= vertical_gap <= 0.8 * line_height and abs(left_shift) <= max(12.0, line_height)


def reflow_narration_lines(
    blocks: list[DocumentBlock], replacements: dict[str, str] | None = None
) -> str:
    """Preserve headings and breaks while joining clear PDF soft-wrapped body lines.

    No source blocks are mutated. Explicit ASCII hyphens are retained (they may
    belong to a compound word); only Unicode soft hyphens are discarded at wraps.
    """
    replacements = replacements or {}
    paragraphs: list[str] = []
    current = ""
    previous: DocumentBlock | None = None
    for block in blocks:
        text = replacements.get(block.id, block.text).strip()
        if not text:
            # An excluded running header/footer should not force a new paragraph.
            continue
        if current and previous is not None and _is_wrapped_line(previous, block):
            if current.endswith("\u00ad"):
                current = current[:-1] + text
            elif current.endswith("-") and text[:1].islower():
                current += text
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
