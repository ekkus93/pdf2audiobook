"""Tiny raster decorations must not turn prose into figure captions."""

from pdf2audiobook.special_material import caption_line_indices


def test_tiny_raster_near_explicit_figure_label_is_not_caption_evidence():
    class Page:
        @staticmethod
        def get_image_info():
            return [{"bbox": (10, 90, 19, 99)}]

    lines = [{"text": "Figure 1: A textual example", "bbox": (10, 100, 150, 112)}]
    original = [line.copy() for line in lines]

    indices, warnings = caption_line_indices(Page(), lines, [], page_number=2)

    assert indices == set()
    assert warnings == []
    assert lines == original


def test_sizable_raster_still_anchors_a_nearby_caption():
    class Page:
        @staticmethod
        def get_image_info():
            return [{"bbox": (10, 10, 110, 90)}]

    lines = [{"text": "Figure 2: A diagram", "bbox": (10, 100, 110, 112)}]
    indices, warnings = caption_line_indices(Page(), lines, [], page_number=3)

    assert indices == {0}
    assert len(warnings) == 1
    assert "preserved verbatim" in warnings[0]


def test_tiny_rasters_do_not_affect_table_caption_classification():
    class Page:
        @staticmethod
        def get_image_info():
            return [{"bbox": (10, 90, 19, 99)}]

    lines = [{"text": "Table 2: Results", "bbox": (10, 100, 110, 112)}]
    indices, warnings = caption_line_indices(
        Page(), lines, [(10, 10, 110, 90)], page_number=4
    )

    assert indices == {0}
    assert len(warnings) == 1
