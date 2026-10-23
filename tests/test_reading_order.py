"""Reading-order geometry must not drop or duplicate PDF text."""

import pytest

from pdf2audiobook.reading_order import order_two_columns


def line(text, x, y, width=180):
    return {"text": text, "bbox": (x, y, x + width, y + 12)}


def test_aligned_columns_are_read_top_to_bottom():
    lines = [
        entry
        for n in range(5)
        for entry in (
            line(f"L{n}", 50, 100 + n * 24),
            line(f"R{n}", 335, 100 + n * 24),
        )
    ]
    ordered, changed = order_two_columns(lines, 600)
    assert changed
    assert [entry["text"] for entry in ordered] == [
        "L0",
        "L1",
        "L2",
        "L3",
        "L4",
        "R0",
        "R1",
        "R2",
        "R3",
        "R4",
    ]
    assert sorted(map(id, lines)) == sorted(map(id, ordered))


def test_full_width_heading_is_not_reordered():
    heading = line("Chapter 1", 40, 50, 510)
    lines = [heading] + [
        entry
        for n in range(5)
        for entry in (
            line(f"L{n}", 50, 100 + n * 24),
            line(f"R{n}", 335, 100 + n * 24),
        )
    ]
    ordered, changed = order_two_columns(lines, 600)
    assert changed and ordered[0] is heading


def test_sparse_or_short_table_cells_are_unchanged():
    for count, width in ((2, 180), (5, 50)):
        lines = [
            entry
            for n in range(count)
            for entry in (
                line(f"Item {n}", 50, 100 + n * 24, width),
                line(f"Price {n}", 335, 100 + n * 24, width),
            )
        ]
        ordered, changed = order_two_columns(lines, 600)
        assert not changed and ordered == lines


@pytest.mark.parametrize("bad_x", [-35, 490])
def test_out_of_page_column_geometry_keeps_original_order(bad_x):
    lines = [
        entry
        for n in range(5)
        for entry in (
            line(f"L{n}", bad_x, 100 + n * 24),
            line(f"R{n}", 335, 100 + n * 24),
        )
    ]
    ordered, changed = order_two_columns(lines, 600)
    assert not changed
    assert ordered == lines
    assert all(before is after for before, after in zip(lines, ordered, strict=True))


def test_small_page_edge_rounding_does_not_disable_valid_column_order():
    lines = [
        entry
        for n in range(5)
        for entry in (
            line(f"L{n}", -0.5, 100 + n * 24),
            line(f"R{n}", 335, 100 + n * 24),
        )
    ]
    ordered, changed = order_two_columns(lines, 600)
    assert changed
    assert [entry["text"] for entry in ordered] == [
        *(f"L{n}" for n in range(5)),
        *(f"R{n}" for n in range(5)),
    ]


@pytest.mark.parametrize("bad_record", [None, "corrupt", 7, ["stray"], float("nan")])
def test_malformed_line_records_preserve_order_and_identity(bad_record):
    lines = [
        entry
        for n in range(5)
        for entry in (
            line(f"L{n}", 50, 100 + n * 24),
            line(f"R{n}", 335, 100 + n * 24),
        )
    ]
    lines.insert(5, bad_record)
    ordered, changed = order_two_columns(lines, 600)
    assert not changed
    assert len(ordered) == len(lines)
    assert all(before is after for before, after in zip(lines, ordered, strict=True))
