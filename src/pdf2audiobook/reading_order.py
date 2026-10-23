"""Conservative geometric reading order for clearly separated prose columns."""

from __future__ import annotations

import math


def order_two_columns(lines: list[dict], page_width: float) -> tuple[list[dict], bool]:
    """Preserve all lines; reorder only sustained aligned prose columns.

    Full-width text acts as a section boundary. Sparse notes, tables, and
    ambiguous layouts retain their original extraction order for review.
    """
    # Geometry comes from a PDF parser. Reject invalid page dimensions without
    # speculatively changing the order of any source text.
    if isinstance(page_width, bool):
        return lines, False
    try:
        width = float(page_width)
    except (TypeError, ValueError, OverflowError):
        return lines, False
    if not math.isfinite(width) or width <= 0 or len(lines) < 8:
        return lines, False
    middle = width / 2
    gap = max(8.0, width * 0.012)

    def bbox(line: dict) -> tuple[float, float, float, float] | None:
        # Malformed adapter records cannot establish column geometry. Treat
        # them as section anchors and preserve the original item identity.
        if not isinstance(line, dict):
            return None
        raw = line.get("bbox")
        if not isinstance(raw, (list, tuple)) or len(raw) != 4:
            return None
        if any(isinstance(n, bool) or not isinstance(n, (float, int)) for n in raw):
            return None
        try:
            x0, y0, x1, y1 = map(float, raw)
        except (TypeError, ValueError, OverflowError):
            return None
        if not all(math.isfinite(n) for n in (x0, y0, x1, y1)):
            return None
        if x1 <= x0 or y1 <= y0:
            return None
        # Out-of-page geometry is unreliable for inferring columns. A small
        # tolerance admits harmless PDF floating-point/crop-edge drift, but
        # large excursions must keep the original source order for review.
        tolerance = max(1.0, width * 0.002)
        if x0 < -tolerance or x1 > width + tolerance:
            return None
        return x0, y0, x1, y1

    def side(line: dict) -> str:
        b = bbox(line)
        if b is None:
            return "anchor"
        if b[2] < middle - gap:
            return "left"
        if b[0] > middle + gap:
            return "right"
        return "anchor"

    def region_order(region: list[dict]) -> tuple[list[dict], bool]:
        # Narrow the validated bounding-box type before sorting by geometry.
        # If a line cannot be classified, retain the original region verbatim.
        left: list[tuple[int, dict, tuple[float, float, float, float]]] = []
        right: list[tuple[int, dict, tuple[float, float, float, float]]] = []
        for index, line in enumerate(region):
            bounds = bbox(line)
            if bounds is None:
                return region, False
            if bounds[2] < middle - gap:
                left.append((index, line, bounds))
            elif bounds[0] > middle + gap:
                right.append((index, line, bounds))
            else:
                return region, False
        if len(left) < 4 or len(right) < 4:
            return region, False
        for column in (left, right):
            widths = sorted(b[2] - b[0] for _, _, b in column)
            if widths[len(widths) // 2] < width * 0.24:
                return region, False
        top = max(min(b[1] for _, _, b in left), min(b[1] for _, _, b in right))
        bottom = min(max(b[3] for _, _, b in left), max(b[3] for _, _, b in right))
        if bottom <= top:
            return region, False
        aligned = sum(
            any(
                abs((a[1] + a[3] - b[1] - b[3]) / 2) <= max(a[3] - a[1], b[3] - b[1]) * 0.75
                for _, _, b in right
            )
            for _, _, a in left
        )
        if aligned < 3:
            return region, False
        ordered = sorted(left, key=lambda item: (item[2][1], item[2][0], item[0]))
        ordered += sorted(right, key=lambda item: (item[2][1], item[2][0], item[0]))
        return [line for _, line, _ in ordered], True

    result: list[dict] = []
    segment: list[dict] = []
    changed = False
    for line in lines:
        if side(line) == "anchor":
            ordered, done = region_order(segment)
            result.extend(ordered)
            result.append(line)
            segment = []
            changed |= done
        else:
            segment.append(line)
    ordered, done = region_order(segment)
    result.extend(ordered)
    return result, changed or done


def _line_box(line: object) -> tuple[float, float, float, float] | None:
    if not isinstance(line, dict) or not isinstance(line.get("text"), str):
        return None
    raw = line.get("bbox")
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    if any(isinstance(n, bool) or not isinstance(n, (float, int)) for n in raw):
        return None
    try:
        x0, y0, x1, y1 = map(float, raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if not all(math.isfinite(n) for n in (x0, y0, x1, y1)) or x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def merge_line_fragments(lines: list[dict]) -> list[dict]:
    """Join word-group fragments that form one printed line.

    Scanned-book text layers often split a line into several word groups,
    which would otherwise read as separate paragraphs. Only consecutive,
    left-to-right fragments sharing a baseline, separated by at most a wide
    word space, are joined. A gap at an edge where several page lines also
    end or start is a column gutter or table column and is never bridged.
    Merged records keep their original fragments under "parts".
    """
    boxes = [_line_box(line) for line in lines]
    starts = [box[0] for box in boxes if box]
    ends = [box[2] for box in boxes if box]

    def aligned(edges: list[float], value: float) -> bool:
        # The fragment's own edge is included in the list, hence one extra.
        return sum(abs(edge - value) <= 2.0 for edge in edges) >= 5

    result: list[dict] = []
    previous: tuple[float, float, float, float] | None = None
    for line, box in zip(lines, boxes):
        if box is not None and previous is not None and result:
            height = min(previous[3] - previous[1], box[3] - box[1])
            overlap = min(previous[3], box[3]) - max(previous[1], box[1])
            gap = box[0] - previous[2]
            if (
                overlap >= 0.5 * height
                and -0.25 * height <= gap <= 1.5 * height
                and not aligned(ends, previous[2])
                and not aligned(starts, box[0])
            ):
                target = result[-1]
                parts = target.get("parts", [target])
                union = (
                    min(previous[0], box[0]),
                    min(previous[1], box[1]),
                    max(previous[2], box[2]),
                    max(previous[3], box[3]),
                )
                size = max(
                    (part.get("size") for part in (*parts, line)),
                    key=lambda value: value if isinstance(value, (int, float)) else 0.0,
                )
                result[-1] = {
                    "text": f"{target['text']} {line['text']}",
                    "bbox": union,
                    "font": target.get("font"),
                    "size": size,
                    "parts": [*parts, line],
                }
                previous = union
                continue
        result.append(line)
        previous = box
    return result
