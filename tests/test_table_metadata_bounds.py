"""Malformed table metadata must not hang or interrupt PDF extraction."""

from itertools import repeat
from types import SimpleNamespace

import pytest

from pdf2audiobook.pdf import _table_regions


class Page:
    def __init__(self, tables):
        self.tables = tables

    def find_tables(self):
        return SimpleNamespace(tables=self.tables)


def test_table_geometry_accepts_valid_rectangle_iterables():
    class Rectangle:
        def __iter__(self):
            return iter((10, 20, 110, 80))

    boxes, warnings = _table_regions(
        Page([SimpleNamespace(bbox=Rectangle())]), page_number=3
    )
    assert boxes == [(10.0, 20.0, 110.0, 80.0)]
    assert warnings == [
        "Page 3: possible table detected; "
        "verify cell order and narration; source text preserved"
    ]


@pytest.mark.parametrize("bbox", [
    iter((10, 20, 110, 80, 90)),
    (10, 20, float("nan"), 80),
    ("bad", 20, 110, 80),
    None,
])
def test_malformed_table_boxes_are_ignored(bbox):
    assert _table_regions(
        Page([SimpleNamespace(bbox=bbox)]), page_number=3
    ) == ([], [])


def test_infinite_table_rectangle_iterator_is_bounded():
    def endless():
        yield from repeat(1)

    assert _table_regions(
        Page([SimpleNamespace(bbox=endless())]), page_number=3
    ) == ([], [])


def test_infinite_table_inventory_is_bounded_and_warns():
    def tables():
        while True:
            yield SimpleNamespace(bbox=(10, 20, 110, 80))

    boxes, warnings = _table_regions(Page(tables()), page_number=8)
    assert len(boxes) == 500
    assert warnings == [
        "Page 8: table inspection truncated; review complex layouts manually"
    ]
