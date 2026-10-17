"""Conservative geometry-backed figure and table caption classification.

This module only labels source lines for human review; it never invents image
descriptions, reorders table cells, or modifies narration/transcript text.
"""
from __future__ import annotations

import math
import re

_CAPTION = re.compile(
    r"^\s*(?P<kind>fig(?:ure)?\.?|table)\s+"
    r"\d{1,3}[a-z]?[\s]*[:.\u2014\u2013-]\s+\S",
    re.IGNORECASE,
)


def _valid_box(box: object) -> tuple[float, float, float, float] | None:
    # PyMuPDF drawing rectangles are fitz.Rect iterables, not list/tuple.
    if not isinstance(box, (list, tuple)):
        try:
            box = tuple(box)
        except (TypeError, ValueError, OverflowError):
            return None
    if len(box) != 4:
        return None
    if any(
        isinstance(v, bool) or not isinstance(v, (int, float))
        or not math.isfinite(v) for v in box
    ):
        return None
    x0, y0, x1, y1 = (float(v) for v in box)
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def _near_region(
    line: tuple[float, float, float, float],
    region: tuple[float, float, float, float],
) -> bool:
    """Require a nearby, horizontally aligned region, not mere co-occurrence."""
    overlap = min(line[2], region[2]) - max(line[0], region[0])
    if overlap < 0.25 * min(line[2] - line[0], region[2] - region[0]):
        return False
    # Reject text inside an image/table: a scanned page is not a caption.
    if line[1] < region[3] and region[1] < line[3]:
        return False
    gap = min(abs(line[1] - region[3]), abs(region[1] - line[3]))
    return gap <= max(32.0, 3 * (line[3] - line[1]))


def caption_line_indices(
    page: object,
    lines: list[dict],
    table_regions: list[tuple[float, float, float, float]],
    *,
    page_number: int,
) -> tuple[set[int], list[str]]:
    """Identify only explicit, nearby figure/table labels for audit.

    An explicit 'Figure 1: ...' without a nearby detected image is still
    ordinary source text. 'Figure 1 shows ...' is prose, not a caption.
    """
    image_boxes: list[tuple[float, float, float, float]] = []
    detector = getattr(page, "get_image_info", None)
    if callable(detector):
        try:
            image_boxes = [
                box for item in detector()
                if isinstance(item, dict)
                if (box := _valid_box(item.get("bbox"))) is not None
            ]
        except Exception:
            # _special_material_warnings handles image-inspection failures.
            pass
    table_boxes = [
        box for item in table_regions
        if (box := _valid_box(item)) is not None
    ]
    identified: set[int] = set()
    for index, item in enumerate(lines):
        text = item.get("text")
        if not isinstance(text, str) or len(text) > 180 or len(text.split()) > 30:
            continue
        match = _CAPTION.match(text)
        box = _valid_box(item.get("bbox"))
        if match is None or box is None:
            continue
        kind = match.group("kind").lower()
        regions = table_boxes if kind == "table" else image_boxes
        if any(_near_region(box, region) for region in regions):
            identified.add(index)
    if not identified:
        return set(), []
    return identified, [
        f"Page {page_number}: {len(identified)} geometry-backed caption(s) "
        "classified for review; original text preserved verbatim"
    ]


def vector_artwork_warnings(page: object, *, page_number: int) -> list[str]:
    """Flag vector-only diagrams that image enumeration cannot see.

    Require multiple sizable drawing paths to avoid mistaking text underlines
    or a single page border for a diagram. This is a review signal only.
    """
    detector = getattr(page, "get_drawings", None)
    crop = getattr(page, "cropbox", None)
    if not callable(detector) or crop is None:
        return []
    try:
        area = max(1.0, float(crop.width) * float(crop.height))
        drawings = detector()
    except Exception:
        return [
            f"Page {page_number}: vector drawing inspection unavailable; "
            "review diagrams manually"
        ]
    count = 0
    for item in drawings[:5000]:
        if not isinstance(item, dict):
            continue
        box = _valid_box(item.get("rect"))
        if box is None:
            continue
        width = box[2] - box[0]
        height = box[3] - box[1]
        if width >= 20 and height >= 20 and width * height >= 0.001 * area:
            count += 1
            if count >= 2:
                return [
                    f"Page {page_number}: substantial vector artwork detected; "
                    "verify diagrams, tables and narration manually; source text preserved"
                ]
    if len(drawings) > 5000:
        return [
            f"Page {page_number}: unusually complex vector drawing content; "
            "review diagrams and narration manually"
        ]
    return []
