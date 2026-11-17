"""Page geometry: bounding boxes, body lines beside a candidate, and the running heads of a page."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from pdf2audiobook.document.page_numbers import PAGE_NUMBER, _number_value, _running_parts
from pdf2audiobook.models import DocumentBlock


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


@dataclass
class _PageGeometry:
    """Untrusted page sizes and labels, with each page's blocks and text extent."""

    sizes: list[tuple[float, float]]
    page_labels: list[str | None] | None
    blocks_by_page: dict[int, list[DocumentBlock]]
    extents: dict[int, tuple[float, float]]

    def valid_page(self, page_index: int) -> bool:
        """Whether a page has a usable size; anything else is missing evidence."""
        # Treat untrusted/malformed page sizes as missing evidence. In
        # particular, isfinite() raises for strings and huge Python integers.
        if not 0 <= page_index < len(self.sizes):
            return False
        dimensions = self.sizes[page_index]
        if not isinstance(dimensions, (tuple, list)) or len(dimensions) != 2:
            return False
        return all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and 0 < value <= 1_000_000
            and math.isfinite(value)
            for value in dimensions
        )

    def positions(self, block: DocumentBlock) -> tuple[float, float]:
        """Horizontal center relative to the paper and to the page's text."""
        assert block.bbox is not None
        center = (block.bbox[0] + block.bbox[2]) / 2
        left, right = self.extents.get(block.page_index, (0.0, 0.0))
        paper = center / self.sizes[block.page_index][0]
        if right - left >= 0.4 * self.sizes[block.page_index][0]:
            return paper, (center - left) / (right - left)
        return paper, paper

    def label_matches(self, page: int, value: int, notation: str) -> bool:
        """Whether a folio agrees with the page's PDF label; no label agrees."""
        labels = self.page_labels
        if labels is None or page >= len(labels) or labels[page] is None:
            return True
        parsed = _number_value(str(labels[page]).strip())
        return parsed is None or parsed == (value, notation)


def _page_geometry(
    blocks: list[DocumentBlock],
    sizes: list[tuple[float, float]],
    page_labels: list[str | None] | None,
) -> _PageGeometry:
    """Group blocks by page and measure each page's horizontal text extent."""
    blocks_by_page: dict[int, list[DocumentBlock]] = defaultdict(list)
    # Scanned pages drift sideways; measure folio placement against each
    # page's text extent rather than the paper edge.
    extents: dict[int, tuple[float, float]] = {}
    for block in blocks:
        blocks_by_page[block.page_index].append(block)
        if block.bbox and _valid_bbox(block.bbox):
            left, right = extents.get(block.page_index, (block.bbox[0], block.bbox[2]))
            extents[block.page_index] = (min(left, block.bbox[0]), max(right, block.bbox[2]))
    return _PageGeometry(sizes, page_labels, blocks_by_page, extents)


def _running_heads(
    blocks: list[DocumentBlock], geometry: _PageGeometry
) -> tuple[set[tuple[str, str]], set[str]]:
    """Find the running titles and collect the text of every body line.

    Returns the (band, title key) pairs repeated in a margin band on three or
    more pages, and the normalized text of each line inside a page body.
    """
    body_text: set[str] = set()
    # Titles repeated in a margin band on three or more pages are running
    # heads, whether or not a folio shares their line.
    title_pages: dict[tuple[str, str], set[int]] = defaultdict(set)
    for block in blocks:
        if (
            not block.bbox
            or not _valid_bbox(block.bbox)
            or not geometry.valid_page(block.page_index)
        ):
            continue
        height = geometry.sizes[block.page_index][1]
        if block.bbox[1] >= 0.12 * height and block.bbox[3] <= 0.88 * height:
            body_text.add(" ".join(block.text.split()).casefold())
        elif block.bbox[3] < 0.12 * height or block.bbox[1] > 0.88 * height:
            text = block.text.strip()
            # Only short, unpunctuated title-like lines can be running heads.
            if len(text.split()) < 8 and not text.endswith((".", "?", "!", ",", ";", ":")):
                band_name = "header" if block.bbox[3] < 0.12 * height else "footer"
                title_pages[(band_name, _running_parts(text)[0])].add(block.page_index)
    running_titles = {key for key, pages in title_pages.items() if len(pages) >= 3}
    return running_titles, body_text


def _continuous_with_body(
    block: DocumentBlock,
    band: str,
    geometry: _PageGeometry,
    *,
    running_title: bool,
    embedded_folio: str | None,
) -> bool:
    """Fail closed when the apparent margin element is continuous with body text."""
    # Fail closed when the apparent margin element is continuous with
    # nearby body text; repeated dialogue and list labels are not folios.
    # A title repeated on three or more pages with its folio is not.
    return (
        not (running_title and embedded_folio is not None)
        and _adjacent_body_line(block, geometry.blocks_by_page[block.page_index], band)
        and block.kind != "footnote"
    )
