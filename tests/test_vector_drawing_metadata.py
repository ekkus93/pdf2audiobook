"""Malformed vector drawing metadata must not interrupt PDF extraction."""

from types import SimpleNamespace

import pytest

from pdf2audiobook.special_material import (
    _vector_caption_regions,
    caption_line_indices,
    vector_artwork_warnings,
)


@pytest.mark.parametrize("returned", [None, {}, 5, "not drawing metadata"])
def test_unexpected_drawing_results_fail_conservatively(returned):
    class Page:
        cropbox = SimpleNamespace(width=600, height=800)

        def get_drawings(self):
            return returned

        def get_image_info(self):
            return []

    page = Page()
    assert _vector_caption_regions(page) == []
    warnings = vector_artwork_warnings(page, page_number=3)
    assert len(warnings) == 1
    assert "inspection unavailable" in warnings[0]
    lines = [{"text": "Figure 1: Illustration", "bbox": (50, 200, 240, 215)}]
    labels, warnings = caption_line_indices(page, lines, [], page_number=3)
    assert labels == set()
    assert warnings == []


def test_valid_vector_drawing_sequence_still_detects_reviewable_artwork():
    class Page:
        cropbox = SimpleNamespace(width=600, height=800)

        def get_drawings(self):
            return (
                {"rect": (50, 100, 170, 170)},
                {"rect": (60, 175, 180, 245)},
            )

        def get_image_info(self):
            return []

    page = Page()
    assert _vector_caption_regions(page)
    assert vector_artwork_warnings(page, page_number=2)
    lines = [{"text": "Figure 1: Two boxes", "bbox": (50, 255, 240, 270)}]
    labels, warnings = caption_line_indices(page, lines, [], page_number=2)
    assert labels == {0}
    assert len(warnings) == 1
