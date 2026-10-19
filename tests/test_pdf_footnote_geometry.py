"""Footnote classification must fail closed on malformed PDF geometry."""

import pytest

from pdf2audiobook.pdf import _footnote_line_indices


def line(text, bbox, size):
    return {"text": text, "bbox": bbox, "size": size}


def sample_lines(extra=None):
    lines = [
        line("A full paragraph of normal prose.", (50, 100, 420, 114), 12),
        line("Another ordinary prose paragraph.", (50, 130, 420, 144), 12),
    ]
    if extra is not None:
        lines.append(extra)
    lines.append(line("1 A small-font footnote.", (50, 750, 240, 760), 7))
    return lines


@pytest.mark.parametrize(
    "bad_bbox",
    [
        (10**400, 600, 10**400 + 20, 612),
        (50, 600, 10**400, 612),
        (float("nan"), 600, 230, 612),
        (50, float("inf"), 230, 612),
        (True, 600, 230, 612),
        ("50", 600, 230, 612),
        (50, 600, 230),
        None,
    ],
)
def test_invalid_intervening_geometry_does_not_crash_or_hide_valid_note(bad_bbox):
    lines = sample_lines(line("Malformed PDF metadata", bad_bbox, 7))
    assert _footnote_line_indices(lines, page_height=842, table_regions=[]) == {3}


@pytest.mark.parametrize("bad_size", [10**400, float("nan"), float("inf"), True, "7", -1])
def test_invalid_font_sizes_are_ignored(bad_size):
    lines = sample_lines(line("Malformed font metadata", (50, 600, 240, 612), bad_size))
    assert _footnote_line_indices(lines, page_height=842, table_regions=[]) == {3}


@pytest.mark.parametrize("height", [0, -842, True, float("nan"), float("inf"), 10**400, None])
def test_invalid_page_height_preserves_unclassified_source(height):
    assert _footnote_line_indices(sample_lines(), page_height=height, table_regions=[]) == set()


def test_valid_anchor_and_same_column_continuation_still_classified():
    lines = sample_lines()
    lines.append(line("The continuation remains part of the note.", (55, 763, 240, 773), 7))
    assert _footnote_line_indices(lines, page_height=842, table_regions=[]) == {2, 3}


def test_malformed_continuation_breaks_grouping_without_false_classification():
    lines = sample_lines()
    lines.extend(
        [
            line("Invalid continuation", (10**400, 763, 10**400 + 5, 773), 7),
            line("Not an inferred continuation", (55, 776, 240, 786), 7),
        ]
    )
    assert _footnote_line_indices(lines, page_height=842, table_regions=[]) == {2}
