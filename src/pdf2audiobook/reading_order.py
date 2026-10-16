"""Conservative geometric reading order for clearly separated prose columns."""
from __future__ import annotations

import math


def order_two_columns(
    lines: list[dict], page_width: float
) -> tuple[list[dict], bool]:
    """Preserve all lines; reorder only sustained aligned prose columns.

    Full-width text acts as a section boundary. Sparse notes, tables, and
    ambiguous layouts retain their original extraction order for review.
    """
    if page_width <= 0 or len(lines) < 8:
        return lines, False
    middle = page_width / 2
    gap = max(8.0, page_width * 0.012)

    def bbox(line: dict) -> tuple[float, float, float, float] | None:
        raw = line.get("bbox")
        if not isinstance(raw, (list, tuple)) or len(raw) != 4:
            return None
        if any(not isinstance(n, (float, int)) or not math.isfinite(n) for n in raw):
            return None
        x0, y0, x1, y1 = map(float, raw)
        return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None

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
        left = [(i, line, bbox(line)) for i, line in enumerate(region)
                if side(line) == "left"]
        right = [(i, line, bbox(line)) for i, line in enumerate(region)
                 if side(line) == "right"]
        if len(left) < 4 or len(right) < 4:
            return region, False
        for column in (left, right):
            widths = sorted(b[2] - b[0] for _, _, b in column)
            if widths[len(widths) // 2] < page_width * 0.24:
                return region, False
        top = max(min(b[1] for _, _, b in left), min(b[1] for _, _, b in right))
        bottom = min(max(b[3] for _, _, b in left), max(b[3] for _, _, b in right))
        if bottom <= top:
            return region, False
        aligned = sum(
            any(abs((a[1] + a[3] - b[1] - b[3]) / 2)
                <= max(a[3] - a[1], b[3] - b[1]) * 0.75
                for _, _, b in right)
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
