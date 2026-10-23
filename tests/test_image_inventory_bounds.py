"""Image metadata inventory limits are conservative review evidence."""

from types import SimpleNamespace

from pdf2audiobook.pdf import _special_material_warnings


class FakeImagePage:
    cropbox = SimpleNamespace(width=600, height=800)

    def __init__(self, images):
        self.images = images

    def get_image_info(self):
        return self.images


def test_image_inventory_is_bounded_and_review_warning_survives():
    images = [{"bbox": (0, 0, 120, 120)}] * 5001
    warnings = _special_material_warnings(FakeImagePage(images), [], page_number=7)
    assert any("image inventory truncated" in warning for warning in warnings)
    assert any("embedded image detected" in warning for warning in warnings)


def test_small_image_inventory_is_not_marked_truncated():
    warnings = _special_material_warnings(
        FakeImagePage([{"bbox": (0, 0, 120, 120)}]),
        [],
        page_number=2,
    )
    assert not any("truncated" in warning for warning in warnings)
    assert any("embedded image detected" in warning for warning in warnings)


def test_nonsequence_image_metadata_keeps_manual_review_warning():
    warnings = _special_material_warnings(
        FakeImagePage(iter([{"bbox": (0, 0, 120, 120)}])),
        [],
        page_number=3,
    )
    assert any("could not inspect embedded images" in warning for warning in warnings)
