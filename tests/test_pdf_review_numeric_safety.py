"""Malformed PDF numeric metadata must never discard or reorder source text."""

from types import SimpleNamespace

import pytest

from pdf2audiobook.pdf import _lines, _special_material_warnings, page_review_warnings


class FakePage:
    cropbox = SimpleNamespace(width=600, height=800)

    def get_image_info(self):
        return []


@pytest.mark.parametrize("invalid", [10**400, float("inf"), float("nan"), True, "7", None])
def test_extracted_span_invalid_font_size_is_conservative(invalid):
    class Page(FakePage):
        def get_text(self, *args, **kwargs):
            return {
                "blocks": [
                    {
                        "lines": [
                            {
                                "bbox": (40, 700, 250, 712),
                                "spans": [{"text": "Preserved footnote content", "size": invalid}],
                            }
                        ],
                    }
                ],
            }

    assert _lines(Page()) == [
        {
            "text": "Preserved footnote content",
            "bbox": (40, 700, 250, 712),
            "font": None,
            "size": 0.0,
        }
    ]


@pytest.mark.parametrize("invalid", [10**400, float("inf"), float("nan"), True, "7", None])
def test_special_material_warning_ignores_invalid_font_size(invalid):
    body = [
        {"text": f"Body line {n}", "size": 12, "bbox": (40, 100 + n * 30, 300, 112 + n * 30)}
        for n in range(3)
    ]
    invalid_note = {
        "text": "1 A footnote remains source text.",
        "size": invalid,
        "bbox": (40, 720, 300, 730),
    }
    assert _special_material_warnings(FakePage(), body + [invalid_note], page_number=1) == []


@pytest.mark.parametrize(
    "invalid_bbox",
    [
        (10**400, 100, 10**400 + 200, 112),
        (40, float("nan"), 200, 112),
        (40, 100, float("inf"), 112),
        (True, 100, 200, 112),
        (40, 100, 200),
        "not a rectangle",
    ],
)
def test_review_warning_ignores_invalid_bbox(invalid_bbox):
    lines = [{"text": f"Preserved line {n}", "bbox": invalid_bbox} for n in range(5)]
    assert page_review_warnings(lines, page_number=2, origin="embedded") == []


def test_valid_small_font_note_and_side_by_side_warnings_still_work():
    body = [
        {"text": f"Body line {n}", "size": 12, "bbox": (40, 100 + n * 30, 300, 112 + n * 30)}
        for n in range(3)
    ]
    note = {"text": "1 Footnote text", "size": 7, "bbox": (40, 720, 300, 730)}
    assert any(
        "small-font footnote" in warning
        for warning in _special_material_warnings(FakePage(), body + [note], page_number=1)
    )
    columns = [
        {"text": f"{side}{n}", "bbox": (x, 100 + n * 24, x + 140, 112 + n * 24)}
        for n in range(3)
        for side, x in (("L", 40), ("R", 330))
    ]
    assert any(
        "multi-column" in warning
        for warning in page_review_warnings(columns, page_number=2, origin="embedded")
    )
