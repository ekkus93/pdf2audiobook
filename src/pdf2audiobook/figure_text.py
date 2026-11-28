"""Figure and table text: the lines inside a drawn figure or a rule-bounded table (TODO F.08).

Diagram labels, chart axes, panel titles and table cells are narrated as they appear, which
breaks up the listening. This module only finds those lines; extraction gives them the block
kind `figure_text`, and analysis omits them from narration only under the explicit
`pdf.figure_text = "omit"` policy, as audited, reversible edits. Captions are not figure text:
they stay narrated.

Two region signals, measured on a figure-heavy research paper (TODO F.08a):

- Clusters of vector drawings at least `FIGURE_MIN_WIDTH` by `FIGURE_MIN_HEIGHT` points. A
  cluster that holds prose (a boxed abstract, a quoted prompt) is not a figure: most of its
  lines are long.
- Tables drawn only with horizontal rules (no cell boxes), found from a "Table N" caption and
  the full-width rules that start just below or end just above it.

A line counts only when it lies inside a region and is set no larger than the page's body text,
so a heading or body paragraph beside a figure is never taken. Every step is bounded and fails
closed: malformed geometry means no figure text, never lost prose.
"""

from __future__ import annotations

import math
import re
from statistics import median
from typing import Any

from pdf2audiobook.special_material import valid_box

Box = tuple[float, float, float, float]

FIGURE_MIN_WIDTH = 60.0
FIGURE_MIN_HEIGHT = 40.0
# A region covering most of the page is a page border or background, not a figure.
FIGURE_MAX_PAGE_SHARE = 0.9
# Prose boxes: this share of their lines has at least LONG_LINE_WORDS words.
LONG_LINE_WORDS = 10
PROSE_BOX_SHARE = 0.6
RULE_MIN_WIDTH = 200.0
RULE_MAX_HEIGHT = 3.0
# Consecutive rules of one table are at most this far apart; the first is this close to its caption.
RULE_GROUP_GAP = 140.0
RULE_CAPTION_GAP = 60.0
# A figure line may be up to this much larger than the page's body text (rounding of sizes).
BODY_SIZE_TOLERANCE = 1.02
_TABLE_CAPTION = re.compile(r"^\s*table\s+\d{1,3}[a-z]?\b", re.IGNORECASE)
_CLUSTER_CAP = 200
_RULE_CAP = 500


def _inside(box: Box, region: Box, pad: float = 2.0) -> bool:
    return (
        box[0] >= region[0] - pad
        and box[1] >= region[1] - pad
        and box[2] <= region[2] + pad
        and box[3] <= region[3] + pad
    )


def _line_box(line: dict) -> Box | None:
    return valid_box(line.get("bbox"))


def _words(line: dict) -> int:
    text = line.get("text")
    return len(text.split()) if isinstance(text, str) else 0


def is_prose_box(lines: list[dict]) -> bool:
    """Whether the lines inside a drawn box read as prose rather than figure labels."""
    counts = [_words(line) for line in lines]
    if len(counts) < 3:
        return False
    return sum(count >= LONG_LINE_WORDS for count in counts) / len(counts) >= PROSE_BOX_SHARE


def drawing_regions(page: Any, drawings: list[dict], lines: list[dict]) -> list[Box]:
    """Figure regions from clusters of the page's vector drawings, prose boxes excluded."""
    cluster = getattr(page, "cluster_drawings", None)
    if not callable(cluster) or not drawings:
        return []
    try:
        width, height = float(page.rect.width), float(page.rect.height)
        clusters = list(cluster(drawings=drawings))[:_CLUSTER_CAP]
    except Exception:
        # Third-party geometry is advisory; without it nothing is figure text.
        return []
    regions = []
    for item in clusters:
        box = valid_box(item)
        if box is None:
            continue
        region_width, region_height = box[2] - box[0], box[3] - box[1]
        if region_width < FIGURE_MIN_WIDTH or region_height < FIGURE_MIN_HEIGHT:
            continue
        if width > 0 and height > 0:
            if region_width * region_height > FIGURE_MAX_PAGE_SHARE * width * height:
                continue
        inside = [line for line in lines if (lb := _line_box(line)) and _inside(lb, box)]
        if is_prose_box(inside):
            continue
        regions.append(box)
    return regions


def _rule_box(rect: object) -> Box | None:
    """A drawing's box, allowing zero height: a stroked line's rectangle is flat."""
    try:
        x0, y0, x1, y1 = (float(value) for value in rect)  # type: ignore[attr-defined]
    except Exception:
        return None
    if not all(math.isfinite(v) for v in (x0, y0, x1, y1)) or x1 <= x0 or y1 < y0:
        return None
    return (x0, y0, x1, y1)


def _rules(drawings: list[dict]) -> list[Box]:
    found = []
    for drawing in drawings[:_RULE_CAP]:
        box = _rule_box(drawing.get("rect")) if isinstance(drawing, dict) else None
        if box and box[2] - box[0] > RULE_MIN_WIDTH and box[3] - box[1] < RULE_MAX_HEIGHT:
            found.append(box)
    return sorted(found, key=lambda rule: rule[1])


def _group(rules: list[Box]) -> list[Box]:
    """The run of rules starting at rules[0], each within RULE_GROUP_GAP of the previous."""
    group = rules[:1]
    for rule in rules[1:]:
        if abs(rule[1] - group[-1][1]) >= RULE_GROUP_GAP:
            break
        group.append(rule)
    return group


def ruled_table_regions(drawings: list[dict], lines: list[dict]) -> list[Box]:
    """Tables drawn with horizontal rules only, anchored on their "Table N" caption.

    The table is the run of full-width rules starting just below the caption (or ending just
    above it, for a caption set under its table); at least two rules make a table.
    """
    rules = _rules(drawings)
    if len(rules) < 2:
        return []
    regions = []
    for line in lines:
        text = line.get("text")
        box = _line_box(line)
        if not isinstance(text, str) or box is None or not _TABLE_CAPTION.match(text):
            continue
        # A caption above its table (the first rule just below it), or else below it.
        group = _group([rule for rule in rules if rule[1] >= box[3]])
        if not group or group[0][1] - box[3] > RULE_CAPTION_GAP:
            above = [rule for rule in reversed(rules) if rule[3] <= box[1]]
            group = list(reversed(_group(above)))
            if not group or box[1] - group[-1][3] > RULE_CAPTION_GAP:
                continue
        if len(group) < 2:
            continue
        regions.append(
            (
                min(rule[0] for rule in group),
                group[0][1] - 1,
                max(rule[2] for rule in group),
                group[-1][3] + 1,
            )
        )
    return regions


def _page_body_size(lines: list[dict], regions: list[Box]) -> float | None:
    """The body text's size on the page, from the lines outside every region, by characters."""
    sized = []
    for line in lines:
        box, size, text = _line_box(line), line.get("size"), line.get("text")
        if box is None or not isinstance(size, (int, float)) or not isinstance(text, str):
            continue
        if any(_inside(box, region) for region in regions):
            continue
        sized.extend([float(size)] * max(1, len(text.strip())))
    return median(sized) if sized else None


def figure_line_indices(
    page: Any,
    lines: list[dict],
    drawings: list[dict],
    *,
    exclude: set[int],
    page_number: int,
) -> tuple[set[int], list[str]]:
    """The indices of the page's figure and table lines, and a review warning if any.

    `exclude` holds lines already classified otherwise (captions, footnotes, equations).
    """
    regions = drawing_regions(page, drawings, lines) + ruled_table_regions(drawings, lines)
    if not regions:
        return set(), []
    body = _page_body_size(lines, regions)
    found = set()
    for index, line in enumerate(lines):
        if index in exclude:
            continue
        box = _line_box(line)
        if box is None or not any(_inside(box, region) for region in regions):
            continue
        size = line.get("size")
        if body is not None and isinstance(size, (int, float)):
            if float(size) > body * BODY_SIZE_TOLERANCE:
                continue
        found.add(index)
    if not found:
        return set(), []
    return found, [
        f"Page {page_number}: {len(found)} line(s) of figure or table text classified; "
        "narrated unless pdf.figure_text is omit"
    ]
