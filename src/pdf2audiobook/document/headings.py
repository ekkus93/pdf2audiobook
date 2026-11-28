"""Heading candidates and the typographic evidence for them."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from pdf2audiobook.document.labels import (
    PAGE_REFERENCE_END,
    ROMAN,
    WRAPPED_LINE_END,
    is_heading_line,
    roman_sequence_heading_indices,
)
from pdf2audiobook.document.pagination import (
    _valid_bbox,
    _wordlike,
)
from pdf2audiobook.models import DocumentBlock


def _space_above(blocks: list[DocumentBlock], index: int, omitted: set[str]) -> str | None:
    """Describe the whitespace separating a line from the text above it.

    Returns "page" when it is the first retained line of its page, "gap"
    when at least half its own line height of space precedes it, "tight"
    when it is packed against the line above, and None without geometry.

    The line above is the nearest earlier line on the page that overlaps this one
    horizontally. A line beside it (the foot of the other column, or a stamp set
    vertically in the margin, such as arXiv's) is not above it; with no line above,
    the line starts its column or area, which counts as a gap.
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
    above_bottom = _bottom_of_line_above(blocks, index, block.bbox, omitted)
    if above_bottom is None:
        return "gap"
    height = block.bbox[3] - block.bbox[1]
    return "gap" if block.bbox[1] - above_bottom >= 0.5 * height else "tight"


def _bottom_of_line_above(
    blocks: list[DocumentBlock], index: int, bbox: tuple[float, ...], omitted: set[str]
) -> float | None:
    """The bottom edge of the nearest earlier line on the page that overlaps `bbox` sideways."""
    page = blocks[index].page_index
    for j in range(index - 1, -1, -1):
        other = blocks[j]
        if other.page_index != page:
            return None
        if other.id in omitted or not other.bbox or not _valid_bbox(other.bbox):
            continue
        if _overlaps_horizontally(bbox, other.bbox):
            return other.bbox[3]
    return None


def _overlaps_horizontally(first: tuple[float, ...], second: tuple[float, ...]) -> bool:
    return min(first[2], second[2]) > max(first[0], second[0])


@dataclass
class _HeadingEvidence:
    """Heading candidates and their evidence, shared by the chapter steps.

    Indices are positions in `blocks`. Each step adds to or narrows
    `heading_indices` in the order `propose_chapters` calls it, and appends
    its warnings to `warnings` in that order too.
    """

    blocks: list[DocumentBlock]
    omitted: set[str]
    contents_titles: dict[int, str]
    heading_indices: list[int]
    typography_ids: set[int]
    warnings: list[str]
    listing_pages: set[int] = field(default_factory=set)
    bookmark_titles: dict[int, str] = field(default_factory=dict)
    numeral_anchored: set[int] = field(default_factory=set)
    first_on_page: dict[int, int] = field(default_factory=dict)
    numeral_titles: dict[int, str] = field(default_factory=dict)
    llm_only: set[int] = field(default_factory=set)


def _typical_body_size(blocks: list[DocumentBlock], omitted: set[str]) -> float | None:
    """The body text's font size: the median by characters, or None with fewer than three lines.

    Weighted by characters, so the many short lines of figures and tables (a paper's diagram
    labels, table cells) cannot outvote the body's long ones: on a figure-heavy paper the
    median line was 8 pt against a 10 pt body.
    """
    # Typography is supporting evidence for unlabeled prose headings. Require
    # substantial size contrast with the body and reject sentence-like prose.
    sized = sorted(
        (float(block.font_size), max(1, len(block.text.strip())))
        for block in blocks
        if block.id not in omitted
        and block.font_size is not None
        and 5 <= float(block.font_size) <= 40
    )
    if len(sized) < 3:
        return None
    half = sum(weight for _size, weight in sized) / 2
    running = 0
    for size, weight in sized:
        running += weight
        if running >= half:
            return size
    return sized[-1][0]


def _is_typographic_heading(
    blocks: list[DocumentBlock], i: int, omitted: set[str], typical_size: float | None
) -> bool:
    """Whether a short, title-like line is set in clearly larger type than the body."""
    block = blocks[i]
    text = block.text.strip()
    return (
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


# An LLM-proposed heading must be set at least this much larger than the body text.
LLM_HEADING_SIZE_RATIO = 1.1


def _llm_heading_plausible(block: DocumentBlock, typical_size: float | None) -> bool:
    """Whether a line the LLM calls a heading could be one, judged by its type.

    A heading is never set smaller than the body text; smaller lines are figure labels,
    table cells and boxed examples, which a model reading the text alone takes for
    headings (on one paper, 36 of the 38 it proposed). Without sizes (a scan) it is kept.
    """
    if block.kind in {"table", "footnote", "caption", "equation", "list"}:
        return False
    if typical_size is None or block.font_size is None or not math.isfinite(block.font_size):
        return True
    return float(block.font_size) >= typical_size * LLM_HEADING_SIZE_RATIO


def _text_headings(
    blocks: list[DocumentBlock],
    omitted: set[str],
    contents_lines: set[int],
    contents_titles: dict[int, str],
    typical_size: float | None,
    extra_heading_ids: set[str] | None,
) -> tuple[list[int], set[int]]:
    """Collect labelled, Roman, LLM, typographic and contents-listed headings.

    Returns the heading indices in book order and the subset supported by
    typography. Lone one-letter numerals are dropped unless longer Roman
    numerals stand beside them.
    """
    heading_indices = []
    typography_ids: set[int] = set()
    roman_sequence = roman_sequence_heading_indices(
        blocks, {j for j, item in enumerate(blocks) if item.id in omitted} | set(contents_lines)
    )
    for i, block in enumerate(blocks):
        if block.id in omitted or i in contents_lines:
            # Entries on a printed contents page are references, not headings.
            continue
        text = block.text.strip()
        is_typographic_heading = _is_typographic_heading(blocks, i, omitted, typical_size)
        if is_typographic_heading:
            typography_ids.add(i)
        if (
            is_heading_line(text)
            or i in roman_sequence
            or (
                block.id in (extra_heading_ids or set())
                and _llm_heading_plausible(block, typical_size)
            )
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
    return heading_indices, typography_ids
