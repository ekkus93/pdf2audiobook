"""Conservative identification of running headers, footers and folios."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict

from pdf2audiobook.config import Pdf as PdfSettings
from pdf2audiobook.models import CleanupEdit, DocumentBlock

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
# One-letter numerals double as initials ("C. DICKENS", "M. LEBLANC"), so they
# only count as headings beside neighbouring numerals or by typography.
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
    # More than one candidate numeral in a single margin band on a page is
    # ambiguous. Non-candidates such as table cells are irrelevant here.
    numeric_counts: dict[tuple[str, int], int] = defaultdict(int)
    for block, band in candidates.values():
        if _number_value(block.text.strip()) is not None:
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
        if ranked and (
            len(ranked) == 1 or ranked[1][0] - ranked[0][0] >= PAGE_NUMBER_EDGE_TIE_TOLERANCE_PT
        ):
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
        tied = False
        if len(ranked_series) > 1 and ranked_series[0][0] == ranked_series[1][0]:
            tied = ranked_series[1][1] - ranked_series[0][1] < PAGE_NUMBER_EDGE_TIE_TOLERANCE_PT
        if ranked_series and (len(ranked_series) == 1 or not tied):
            selected_sequences[page].add(ranked_series[0][2])
        else:
            ambiguous_sequence_pages.add(page)
    if ambiguous_sequence_pages and warnings is not None:
        warnings.append("Multiple page-number sequences retained; verify pagination")
    if ambiguous_sequence_pages and review_reasons is not None:
        review_reasons.add("ambiguous_page_numbers")
    chosen_sequences = {
        series for series_set in selected_sequences.values() for series in series_set
    }
    if (
        page_labels is not None
        and any(
            not page_label_matches(page, page + offset, notation)
            for (_band, offset, notation) in chosen_sequences
            for page in qualifying_sequences[(_band, offset, notation)]
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
