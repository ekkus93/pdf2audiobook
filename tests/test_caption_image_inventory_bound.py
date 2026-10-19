"""Bounded caption inspection of third-party image inventories."""

from pdf2audiobook.special_material import caption_line_indices


def test_caption_image_inventory_stops_at_bounded_limit():
    seen = 0

    def image_info():
        nonlocal seen
        for index in range(5001):
            seen += 1
            if index == 5000:
                raise AssertionError("caption detection consumed beyond image limit")
            yield {"bbox": (10, 10, 110, 90)} if index == 0 else {"bbox": None}

    class Page:
        get_image_info = staticmethod(image_info)

    lines = [{"text": "Figure 1: Example diagram", "bbox": (10, 100, 110, 112)}]
    indices, warnings = caption_line_indices(Page(), lines, [], page_number=3)

    assert seen == 5000
    assert indices == {0}
    assert len(warnings) == 1
    assert "source" not in warnings[0].lower()


def test_caption_image_inventory_finite_generator_still_classifies():
    class Page:
        @staticmethod
        def get_image_info():
            yield {"bbox": (10, 10, 110, 90)}

    lines = [{"text": "Figure 2: Another diagram", "bbox": (10, 100, 110, 112)}]
    indices, warnings = caption_line_indices(Page(), lines, [], page_number=4)

    assert indices == {0}
    assert len(warnings) == 1
