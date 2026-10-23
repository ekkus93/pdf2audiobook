"""Malformed embedded-image metadata must preserve PDF review and extraction."""

from types import SimpleNamespace

import pytest

from pdf2audiobook.pdf import _special_material_warnings


@pytest.mark.parametrize(
    "images",
    [
        None,
        {"bbox": (10, 10, 100, 100)},
        [{"bbox": ("bad", 10, 100, 100)}],
        [{"bbox": (10, 10, float("nan"), 100)}],
        [None],
    ],
)
def test_uninspectable_image_metadata_warns_without_throwing(images):
    class Page:
        cropbox = SimpleNamespace(width=600, height=800)

        def get_image_info(self):
            return images

    warnings = _special_material_warnings(Page(), [], page_number=4)
    assert len(warnings) == 1
    assert "could not inspect embedded images" in warnings[0]


def test_valid_image_geometry_warns_only_for_significant_artwork():
    class Page:
        cropbox = SimpleNamespace(width=600, height=800)

        def __init__(self, bbox):
            self.bbox = bbox

        def get_image_info(self):
            return [{"bbox": self.bbox}]

    assert _special_material_warnings(
        Page((10, 10, 150, 150)),
        [],
        page_number=2,
    ) == [
        "Page 2: embedded image detected; OCR does not describe figures or diagrams; review manually"
    ]
    assert (
        _special_material_warnings(
            Page((10, 10, 20, 20)),
            [],
            page_number=2,
        )
        == []
    )
