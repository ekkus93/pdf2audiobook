"""Review warnings must never remove or rewrite extracted PDF content."""
from pdf2audiobook.pdf import page_review_warnings


def line(text: str, bbox: tuple[float, float, float, float] | None = None) -> dict:
    return {"text": text, "bbox": bbox}


def test_normal_embedded_page_has_no_review_warning() -> None:
    lines = [
        line("A normal first line of prose.", (30, 20, 240, 30)),
        line("A normal second line of prose.", (30, 33, 240, 43)),
    ]
    assert page_review_warnings(lines, page_number=1, origin="embedded") == []


def test_short_ocr_page_requires_review_not_silent_acceptance() -> None:
    warnings = page_review_warnings(
        [line("x")], page_number=4, origin="ocr"
    )
    assert len(warnings) == 1
    assert "Page 4" in warnings[0]
    assert "very little text" in warnings[0]


def test_short_embedded_heading_does_not_trigger_ocr_warning() -> None:
    assert page_review_warnings(
        [line("Chapter 1")], page_number=2, origin="embedded"
    ) == []


def test_suspicious_unicode_replacement_requires_review() -> None:
    warnings = page_review_warnings(
        [line("Bad \ufffd\ufffd glyphs")], page_number=7, origin="ocr"
    )
    assert any("replacement/control" in warning for warning in warnings)


def test_possible_two_column_reading_order_is_flagged() -> None:
    lines = [
        line("Left one", (20, 20, 120, 30)),
        line("Right one", (200, 20, 300, 30)),
        line("Left two", (20, 40, 120, 50)),
        line("Right two", (200, 40, 300, 50)),
    ]
    warnings = page_review_warnings(lines, page_number=3, origin="embedded")
    assert any("reading order" in warning for warning in warnings)


def test_sequential_full_width_lines_not_flagged_as_columns() -> None:
    lines = [
        line("First", (20, 20, 300, 30)),
        line("Second", (20, 40, 300, 50)),
        line("Third", (20, 60, 300, 70)),
    ]
    assert page_review_warnings(lines, page_number=5, origin="embedded") == []
