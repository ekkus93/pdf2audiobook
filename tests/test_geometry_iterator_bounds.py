"""Geometry validation must not exhaust an untrusted bounding-box iterator."""

from pdf2audiobook.special_material import _valid_box


def test_unbounded_rectangle_iterator_is_rejected_after_five_items():
    seen = []

    def endless():
        value = 0
        while True:
            value += 1
            seen.append(value)
            if value > 5:
                raise AssertionError("geometry parser consumed unbounded iterator")
            yield value

    assert _valid_box(endless()) is None
    assert seen == [1, 2, 3, 4, 5]


def test_four_coordinate_rectangle_iterator_is_still_supported():
    class Rectangle:
        def __iter__(self):
            return iter((10, 20, 30, 40))

    assert _valid_box(Rectangle()) == (10.0, 20.0, 30.0, 40.0)


def test_five_coordinate_iterator_is_not_accepted_as_rectangle():
    assert _valid_box(iter((10, 20, 30, 40, 50))) is None


def test_rectangle_iterator_exception_is_nonfatal():
    def broken():
        yield 1
        yield 2
        raise RuntimeError("corrupt vector geometry")

    assert _valid_box(broken()) is None


def test_unreadable_rectangle_iterator_is_nonfatal():
    class BrokenRectangle:
        def __iter__(self):
            raise OSError("unreadable metadata")

    assert _valid_box(BrokenRectangle()) is None


def test_huge_integer_rectangle_coordinates_do_not_crash_geometry_review():
    enormous = 10**1000
    assert _valid_box((0, 0, enormous, 100)) is None
    assert _valid_box(iter((0, 0, enormous, 100))) is None


def test_nonfinite_rectangle_coordinates_are_rejected():
    assert _valid_box((0, 0, float("inf"), 100)) is None
    assert _valid_box((0, float("nan"), 10, 100)) is None


def test_regular_integer_and_float_rectangles_remain_supported():
    assert _valid_box((0, 0.5, 20, 40.0)) == (0.0, 0.5, 20.0, 40.0)
