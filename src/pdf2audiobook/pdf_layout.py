"""Page classification for PDF extraction: page visuals, embedded text lines, tables,
footnotes, special material, block kinds and page review warnings."""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass
from itertools import islice
from typing import Any, Literal

import pymupdf

from pdf2audiobook.document.structure import is_heading_line, is_list_line
from pdf2audiobook.special_material import valid_box


@dataclass(frozen=True)
class _PageVisuals:
    images: list[dict]
    drawings: list[dict]
    image_count: int
    drawing_count: int
    image_unavailable: bool = False
    drawings_unavailable: bool = False


_PAGE_VISUAL_ITEM_CAP = 5000


_BACKGROUND_COVERAGE = 0.95


def _background_only(page_rect: Any, drawings: list[dict]) -> bool:
    """True when every drawing is a fill-only rectangle covering (nearly) the whole page.

    That is how an EPUB renderer paints the page background behind a cover image; it
    is not artwork whose text could be missing.
    """
    try:
        area = float(page_rect.width) * float(page_rect.height)
        return (
            bool(drawings)
            and area > 0
            and all(
                drawing.get("fill") is not None
                and drawing.get("color") is None
                and float(drawing["rect"].width) * float(drawing["rect"].height)
                >= _BACKGROUND_COVERAGE * area
                for drawing in drawings
            )
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def _page_visuals(page: pymupdf.Page) -> _PageVisuals:
    """Read bounded image and vector metadata once for all page heuristics."""
    try:
        raw_images = page.get_image_info()
        if not isinstance(raw_images, (list, tuple)):
            raise ValueError("uninspectable image metadata")
        images = list(raw_images[:_PAGE_VISUAL_ITEM_CAP])
        image_count = len(raw_images)
        image_unavailable = False
    except Exception:
        images, image_count, image_unavailable = [], 0, True
    try:
        raw_drawings = page.get_drawings()
        if not isinstance(raw_drawings, (list, tuple)):
            raise ValueError("uninspectable vector metadata")
        drawings = list(raw_drawings[:_PAGE_VISUAL_ITEM_CAP])
        drawing_count = len(raw_drawings)
        drawings_unavailable = False
    except Exception:
        drawings, drawing_count, drawings_unavailable = [], 0, True
    return _PageVisuals(
        images,
        drawings,
        image_count,
        drawing_count,
        image_unavailable,
        drawings_unavailable,
    )


def _positive_finite_number(value: object) -> float | None:
    """Convert advisory PDF numeric metadata without trusting its magnitude."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _lines(page: pymupdf.Page, textpage: pymupdf.TextPage | None = None) -> list[dict]:
    structure = page.get_text("dict", sort=True, textpage=textpage)
    extracted = []
    for region in structure["blocks"]:
        if "lines" not in region:
            continue
        for line in region["lines"]:
            spans = line.get("spans", [])
            text = "".join(span.get("text", "") for span in spans).strip()
            if not text:
                continue
            bbox = line.get("bbox")
            largest = max(
                (_positive_finite_number(span.get("size")) or 0.0 for span in spans),
                default=0.0,
            )
            font = spans[0].get("font") if spans else None
            extracted.append({"text": text, "bbox": bbox, "font": font, "size": largest})
    return extracted


def page_review_warnings(lines: list[dict], *, page_number: int, origin: str) -> list[str]:
    """Flag suspicious extraction without silently discarding any source text.

    These are review heuristics, not Tesseract confidence scores. In particular,
    horizontally separated text at matching heights may be two columns whose
    reading order cannot be established reliably from sorted PDF lines alone.
    """
    warnings: list[str] = []
    text = " ".join(line["text"] for line in lines)
    if (
        text.count("\ufffd") >= 2
        or sum(ord(char) < 32 and char not in "\t\n\r" for char in text) >= 2
    ):
        warnings.append(
            f"Page {page_number}: suspicious replacement/control characters; "
            "review extracted text against the PDF"
        )
    if origin == "ocr" and lines and len(text.strip()) < 24:
        warnings.append(
            f"Page {page_number}: OCR produced very little text; "
            "verify recognition and page coverage"
        )

    aligned_separate_lines = 0
    for first, second in zip(lines, lines[1:]):
        left, right = valid_box(first.get("bbox")), valid_box(second.get("bbox"))
        if left is None or right is None:
            continue
        overlap = min(left[3], right[3]) - max(left[1], right[1])
        shortest_height = min(left[3] - left[1], right[3] - right[1])
        separated = left[2] + 8 < right[0] or right[2] + 8 < left[0]
        if shortest_height > 0 and overlap > shortest_height * 0.5 and separated:
            aligned_separate_lines += 1
    if aligned_separate_lines >= 2:
        warnings.append(
            f"Page {page_number}: possible multi-column or side-by-side text; "
            "verify reading order before narration"
        )
    return warnings


def _table_regions(
    page: pymupdf.Page, *, page_number: int
) -> tuple[list[tuple[float, float, float, float]], list[str]]:
    """Locate high-confidence table rectangles without altering their text.

    The geometry is used only to label contained source blocks for review.
    Never discard text, synthesize cell descriptions or infer reading order.
    """
    detector = getattr(page, "find_tables", None)
    if not callable(detector):
        return [], []
    try:
        found = detector()
        boxes: list[tuple[float, float, float, float]] = []
        # Table geometry is advisory. Third-party iterators and bbox objects
        # must not hang extraction or exhaust memory on malformed documents.
        for index, table in enumerate(islice(found.tables, 501)):
            if index == 500:
                return boxes, [
                    f"Page {page_number}: table inspection truncated; "
                    "review complex layouts manually"
                ]
            bounds = valid_box(getattr(table, "bbox", None))
            if bounds is not None:
                boxes.append(bounds)
    except Exception:
        return [], [
            f"Page {page_number}: table detection unavailable; review complex layouts manually"
        ]
    if not boxes:
        return [], []
    return boxes, [
        f"Page {page_number}: possible table detected; "
        "verify cell order and narration; source text preserved"
    ]


def _inside_table(
    bbox: tuple[float, float, float, float] | None,
    regions: list[tuple[float, float, float, float]],
) -> bool:
    if bbox is None:
        return False
    return any(
        bbox[0] >= x0 - 2 and bbox[1] >= y0 - 2 and bbox[2] <= x1 + 2 and bbox[3] <= y1 + 2
        for x0, y0, x1, y1 in regions
    )


def _classify_block_kind(
    text: str,
    line_index: int,
    bbox: tuple[float, float, float, float] | None,
    table_regions: list[tuple[float, float, float, float]],
    footnote_indices: set[int],
    caption_indices: set[int],
    equation_indices: set[int],
    *,
    previous_text: str | None,
    next_text: str | None,
    display_heading: bool,
) -> Literal["heading", "paragraph", "list", "table", "footnote", "caption", "equation", "unknown"]:
    """Assign one explicit structural kind after page-level detectors run."""
    if display_heading:
        return "heading"
    if _inside_table(bbox, table_regions):
        return "table"
    if line_index in footnote_indices:
        return "footnote"
    if line_index in caption_indices:
        return "caption"
    if line_index in equation_indices:
        return "equation"
    if is_heading_line(text):
        return "heading"
    if is_list_line(text, previous_text=previous_text, next_text=next_text):
        return "list"
    return "unknown"


def _special_material_warnings(
    page: pymupdf.Page,
    lines: list[dict],
    *,
    page_number: int,
    visuals: _PageVisuals | None = None,
) -> list[str]:
    """Report likely non-prose content without deleting or inventing narration.

    Image presence, small bottom-margin text and mathematical symbols are
    evidence for review, not proof of an image caption, footnote or equation.
    """
    result: list[str] = []
    try:
        images = visuals.images if visuals is not None else page.get_image_info()
        if not isinstance(images, (list, tuple)):
            raise ValueError("uninspectable image metadata")
        if visuals is not None and visuals.image_unavailable:
            raise ValueError("uninspectable image metadata")
        image_count = visuals.image_count if visuals is not None else len(images)
        if image_count > _PAGE_VISUAL_ITEM_CAP:
            result.append(
                f"Page {page_number}: embedded image inventory truncated; "
                "review complex image layouts manually"
            )
        boxes = []
        for info in images[:5000]:
            if not isinstance(info, dict):
                raise ValueError("uninspectable image metadata")
            box = valid_box(info.get("bbox"))
            if box is None:
                raise ValueError("invalid image geometry")
            boxes.append(box)
        page_area = max(1.0, float(page.cropbox.width * page.cropbox.height))
        large_image = any(
            (box[2] - box[0]) * (box[3] - box[1]) / page_area >= 0.01 for box in boxes
        )
    except Exception:
        result.append(
            f"Page {page_number}: could not inspect embedded images; "
            "verify non-text content manually"
        )
    else:
        if large_image:
            result.append(
                f"Page {page_number}: embedded image detected; "
                "OCR does not describe figures or diagrams; review manually"
            )
    # Font and bbox metadata is advisory; reject unrepresentable numeric
    # values rather than allowing malformed PDF metadata to crash inspection.
    sizes = [
        size for line in lines if (size := _positive_finite_number(line.get("size"))) is not None
    ]
    if len(sizes) >= 3:
        median_size = statistics.median(sizes)
        height = _positive_finite_number(page.cropbox.height)
        if height is not None and any(
            (bounds := valid_box(line.get("bbox"))) is not None
            and (size := _positive_finite_number(line.get("size"))) is not None
            and size <= 0.78 * median_size
            and bounds[1] >= 0.7 * height
            for line in lines
        ):
            result.append(
                f"Page {page_number}: possible small-font footnote or endnote; "
                "preserved verbatim for review"
            )
    math_symbols = set("∑∫√≈≤≥∞∂∇∈∉⊂⊆≠∝")
    if any(math_symbols.intersection(line["text"]) for line in lines):
        result.append(
            f"Page {page_number}: mathematical notation detected; "
            "verify spoken rendering against source"
        )
    return result


def _footnote_line_indices(
    lines: list[dict],
    *,
    page_height: float,
    table_regions: list[tuple[float, float, float, float]],
) -> set[int]:
    """Conservatively tag numbered small-type notes separated from body prose.

    Never classify by small font or bottom position alone: a short numbered
    list or ordinary paragraph near the page bottom must remain body text.
    Uncertain notes are preserved as untyped source blocks for review.
    """
    # Geometry is advisory and may originate in a malformed PDF or adapter.
    # A nonfinite page size or unrepresentable coordinate must not interrupt
    # extraction or cause an unverified footnote classification.
    if isinstance(page_height, bool):
        return set()
    try:
        height = float(page_height)
    except (TypeError, ValueError, OverflowError):
        return set()
    if not math.isfinite(height) or height <= 0:
        return set()

    validated: list[tuple[tuple[float, float, float, float] | None, float | None]] = []
    for line in lines:
        bounds = valid_box(line.get("bbox"))
        raw_size = line.get("size")
        size: float | None = None
        if not isinstance(raw_size, bool) and isinstance(raw_size, (int, float)):
            try:
                candidate = float(raw_size)
            except (TypeError, ValueError, OverflowError):
                pass
            else:
                if math.isfinite(candidate) and candidate > 0:
                    size = candidate
        validated.append((bounds, size))

    body_sizes = [
        size
        for bounds, size in validated
        if bounds is not None and size is not None and bounds[1] < height * 0.65
    ]
    if len(body_sizes) < 2:
        return set()
    body_size = statistics.median(body_sizes)
    result: set[int] = set()
    for index, line in enumerate(lines):
        bounds, size = validated[index]
        text = line.get("text")
        if (
            bounds is None
            or size is None
            or size > 0.78 * body_size
            or bounds[1] < height * 0.70
            or _inside_table(bounds, table_regions)
            or not isinstance(text, str)
            or not re.match(r"^(?:\d{1,2}[.)]?|[*†‡])\s+\S", text)
        ):
            continue
        # Require a clear gap from preceding valid text, not merely small font.
        preceding_bottom = max(
            (
                other_bounds[3]
                for other_index, (other_bounds, _) in enumerate(validated)
                if other_index != index
                and other_bounds is not None
                and other_bounds[3] <= bounds[1]
            ),
            default=None,
        )
        if preceding_bottom is None or bounds[1] - preceding_bottom < max(18.0, body_size * 1.5):
            continue
        result.add(index)

    # Extend confirmed footnotes through adjacent, same-column small-type
    # continuation lines only. Never infer a note from small text alone.
    for anchor_index in sorted(result):
        anchor_box = validated[anchor_index][0]
        if anchor_box is None:
            continue
        previous_box = anchor_box
        for next_index in range(anchor_index + 1, len(lines)):
            if next_index in result:
                break
            item = lines[next_index]
            bounds, size = validated[next_index]
            text = item.get("text")
            if (
                bounds is None
                or size is None
                or size > 0.78 * body_size
                or not isinstance(text, str)
                or not text.strip()
                or bounds[1] < height * 0.70
                or _inside_table(bounds, table_regions)
            ):
                break
            if re.match(r"^(?:\d{1,2}[.)]?|[*†‡])\s+\S", text):
                break
            gap = bounds[1] - previous_box[3]
            overlap = min(bounds[2], previous_box[2]) - max(bounds[0], previous_box[0])
            if (
                not -2.0 <= gap <= max(8.0, 0.8 * body_size)
                or overlap <= 0
                or abs(bounds[0] - anchor_box[0]) > max(24.0, 2 * body_size)
            ):
                break
            result.add(next_index)
            previous_box = bounds
    return result | _footnote_zone(lines, validated, height, body_size, table_regions)


_NOTE_ANCHOR = re.compile(r"^(?:\d{1,3}[.)]?\s+\S|\d{1,3}(?=[A-Z])|[*†‡§]\s*\S)")


def _footnote_zone(
    lines: list[dict],
    validated: list[tuple[tuple[float, float, float, float] | None, float | None]],
    height: float,
    body_size: float,
    table_regions: list[tuple[float, float, float, float]],
) -> set[int]:
    """Tag the run of small-type notes that closes a page.

    Scanned books set notes only slightly smaller than the body and close
    beneath it, so a per-line test misses them. Instead require the whole
    run: it starts low on the page after a visible gap, holds at least one
    note marker, is set in smaller type overall and continues to the foot
    of the page. Unnumbered lines at its top continue a note from the
    previous page. A small-type passage followed by body text is not a zone.
    """
    # Unverifiable geometry anywhere on the page: keep every line as text.
    if any(bounds is None or size is None for bounds, size in validated):
        return set()
    boxes = {
        index: (bounds, size)
        for index, (bounds, size) in enumerate(validated)
        if bounds is not None and size is not None
    }
    order = sorted(boxes, key=lambda index: boxes[index][0][1])
    position = len(order) - 1
    # Big-type furniture (a printer's signature mark) may sit under the notes.
    while position >= 0 and boxes[order[position]][1] > 0.95 * body_size:
        if boxes[order[position]][0][1] < height * 0.85:
            return set()
        position -= 1
    zone: list[int] = []
    while position >= 0:
        index = order[position]
        bounds, size = boxes[index]
        text = lines[index].get("text")
        if (
            size > 0.95 * body_size
            or bounds[1] < height * 0.5
            or not isinstance(text, str)
            or not text.strip()
            or _inside_table(bounds, table_regions)
        ):
            break
        if zone:
            # Notes are one tight, single-column run; a gap or a side column
            # ends it.
            below = boxes[zone[-1]][0]
            overlap = min(bounds[2], below[2]) - max(bounds[0], below[0])
            if below[1] - bounds[3] > max(8.0, body_size) or overlap <= 0:
                return set()
        zone.append(index)
        position -= 1
    if not zone or position < 0:
        return set()
    above_bounds, above_size = boxes[order[position]]
    top = boxes[zone[-1]][0]
    if above_size <= 0.95 * body_size or top[1] - above_bounds[3] < max(4.0, 0.5 * body_size):
        return set()
    if statistics.median(boxes[index][1] for index in zone) > 0.86 * body_size:
        return set()
    if not any(_NOTE_ANCHOR.match(str(lines[index]["text"]).strip()) for index in zone):
        return set()
    return set(zone)
