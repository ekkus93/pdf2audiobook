"""Invalid PDF geometry must not crash or reorder text speculatively."""

import pytest

from pdf2audiobook.reading_order import order_two_columns


@pytest.mark.parametrize(
    "width",
    [
        0,
        -600,
        True,
        float("nan"),
        float("inf"),
        10**400,
        "600",
        None,
    ],
)
def test_invalid_page_width_preserves_source_order(width):
    lines = [
        {"text": f"line-{index}", "bbox": (50, 20 * index, 230, 20 * index + 12)}
        for index in range(10)
    ]
    result, changed = order_two_columns(lines, width)
    assert result == lines
    assert all(left is right for left, right in zip(result, lines, strict=True))
    assert changed is False


@pytest.mark.parametrize(
    "bounds",
    [
        (10**400, 100, 10**400 + 200, 112),
        (50, 100, 10**400, 112),
        (True, 100, 230, 112),
        (float("nan"), 100, 230, 112),
        (50, float("inf"), 230, 112),
        ("50", 100, 230, 112),
        (50, 100, 230),
    ],
)
def test_invalid_line_bounds_preserve_text_and_provenance(bounds):
    lines = [{"text": f"line-{index}", "bbox": bounds} for index in range(10)]
    result, changed = order_two_columns(lines, 600)
    assert result == lines
    assert all(left is right for left, right in zip(result, lines, strict=True))
    assert changed is False


def test_bad_bbox_is_an_anchor_between_valid_two_column_regions():
    def line(label, x, y):
        return {"text": label, "bbox": (x, y, x + 180, y + 12)}

    first = [
        item
        for n in range(5)
        for item in (line(f"L{n}", 50, 100 + n * 24), line(f"R{n}", 335, 100 + n * 24))
    ]
    anchor = {"text": "Retain this ambiguous line", "bbox": (10**400, 2, 4, 6)}
    last = [
        item
        for n in range(5)
        for item in (line(f"l{n}", 50, 350 + n * 24), line(f"r{n}", 335, 350 + n * 24))
    ]
    result, changed = order_two_columns(first + [anchor] + last, 600)
    assert changed is True
    assert result[10] is anchor
    assert [entry["text"] for entry in result[:10]] == [
        *(f"L{n}" for n in range(5)),
        *(f"R{n}" for n in range(5)),
    ]
    assert [entry["text"] for entry in result[11:]] == [
        *(f"l{n}" for n in range(5)),
        *(f"r{n}" for n in range(5)),
    ]
