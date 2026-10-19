"""Conservative geometry-backed figure and table caption classification.

This module only labels source lines for human review; it never invents image
descriptions, reorders table cells, or modifies narration/transcript text.
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable
from itertools import islice
from typing import cast

_CAPTION = re.compile(
    r"^\s*(?P<kind>fig(?:ure)?\.?|table)\s+"
    r"\d{1,3}[a-z]?[\s]*[:.\u2014\u2013-]\s+\S",
    re.IGNORECASE,
)


def _valid_box(box: object) -> tuple[float, float, float, float] | None:
    # PyMuPDF drawing rectangles are fitz.Rect iterables, not list/tuple.
    if not isinstance(box, (list, tuple)):
        # fitz.Rect supports tuple(rect) but does not register with the
        # collections.abc.Iterable runtime check. Validate by conversion.
        try:
            box = tuple(islice(cast(Iterable[object], box), 5))
        except Exception:
            # Malformed third-party geometry is advisory, never fatal.
            return None
    if len(box) != 4:
        return None
    coordinates: list[float] = []
    for value in box:
        if (
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            return None
        coordinates.append(float(value))
    x0, y0, x1, y1 = coordinates
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


def _vector_caption_regions(page: object) -> list[tuple[float, float, float, float]]:
    """Find bounded clusters of sizable vector paths near a figure caption.

    A lone page border or rectangle is not enough evidence for a figure.
    Do not inspect page text or treat these rectangles as transcribed content.
    """
    detector = getattr(page, "get_drawings", None)
    crop = getattr(page, "cropbox", None)
    if not callable(detector) or crop is None:
        return []
    try:
        page_area = max(1.0, float(crop.width) * float(crop.height))
        drawings = detector()
    except Exception:
        return []
    # A third-party adapter can return an unexpected object instead of a
    # bounded sequence. Treat it as uninspectable rather than crashing PDF
    # extraction or consuming an unbounded iterator.
    if not isinstance(drawings, (list, tuple)):
        return []
    candidates = []
    for item in drawings[:5000]:
        if not isinstance(item, dict):
            continue
        box = _valid_box(item.get("rect"))
        if box is None:
            continue
        width, height = box[2] - box[0], box[3] - box[1]
        if (
            width >= 20 and height >= 20
            and 0.001 * page_area <= width * height <= 0.6 * page_area
        ):
            candidates.append(box)
            # Pairwise grouping is quadratic; bound it on vector-heavy PDFs.
            # Other substantial artwork remains flagged for manual review by
            # vector_artwork_warnings, never silently described or removed.
            if len(candidates) >= 256:
                break
    regions: list[tuple[float, float, float, float]] = []
    for index, first in enumerate(candidates):
        for second in candidates[index + 1:]:
            horizontal_overlap = min(first[2], second[2]) - max(first[0], second[0])
            if horizontal_overlap < 0.25 * min(
                first[2] - first[0], second[2] - second[0]
            ):
                continue
            vertical_gap = max(
                0.0, first[1] - second[3], second[1] - first[3]
            )
            if vertical_gap > 40:
                continue
            union = (
                min(first[0], second[0]), min(first[1], second[1]),
                max(first[2], second[2]), max(first[3], second[3]),
            )
            if (union[2] - union[0]) * (union[3] - union[1]) > 0.6 * page_area:
                continue
            regions.append(union)
            if len(regions) >= 32:
                return regions
    return regions


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
    vector_boxes = _vector_caption_regions(page)
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
        regions = table_boxes if kind == "table" else image_boxes + vector_boxes
        if any(_near_region(box, region) for region in regions):
            identified.add(index)
    if not identified:
        return set(), []
    return identified, [
        f"Page {page_number}: {len(identified)} geometry-backed caption(s) "
        "classified for review; original text preserved verbatim"
    ]



# Conservative displayed-formula classification. This is not mathematical OCR,
# a parser, or a source of automatically generated spoken descriptions.
_FORMULA_LHS = re.compile(
    r"^(?:[A-Za-z][A-Za-z0-9_]{0,12}|[A-Za-z]\([^)]{1,24}\))"
    r"\s*(?:=|≈|≃|≤|≥|≠)\s*\S"
)
_FORMULA_SIGNS = frozenset("∑∫√≈≤≥∞∂∇∈∉⊂⊆≠∝±×÷∀∃∼≃≅⊥∥²³")


def equation_line_indices(
    lines: list[dict], *, page_number: int,
) -> tuple[set[int], list[str]]:
    """Mark high-confidence short standalone formulas for review only.

    Avoid inferring formulas from ordinary prose containing '=' or an inline
    mathematical symbol. No text is removed, rewritten, or reordered.
    """
    selected: set[int] = set()
    for index, item in enumerate(lines):
        text = item.get("text")
        if not isinstance(text, str):
            continue
        text = text.strip()
        if not text or len(text) > 140 or len(text.split()) > 16:
            continue
        # Sentences, figure captions, lists and URLs are not displayed formulas.
        if text.endswith((".", "?", "!", ";", ":")) or re.match(
            r"^(?:fig(?:ure)?|table|chapter)\s+\d+[:.\s]", text, re.I
        ):
            continue
        is_assignment = _FORMULA_LHS.match(text) is not None
        has_formula_signs = bool(_FORMULA_SIGNS.intersection(text))
        is_symbolic = (
            has_formula_signs
            and (
                text[0] in "∑∫√∂∇∀∃"
                or "=" in text or "≈" in text or "≠" in text
                or "≤" in text or "≥" in text
            )
            and len(text.split()) <= 12
            and (text[:1].isalpha() or text[0] in "∑∫√∂∇∀∃")
        )
        if is_assignment or is_symbolic:
            selected.add(index)
    if not selected:
        return set(), []
    return selected, [
        f"Page {page_number}: {len(selected)} likely displayed equation(s) "
        "classified for review; verify spoken rendering; original text preserved"
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
    if not isinstance(drawings, (list, tuple)):
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
