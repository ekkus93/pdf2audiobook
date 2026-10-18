"""Raster-tile union detection and OCR auto-mode coverage regressions."""

from pathlib import Path
import shutil

import fitz
import pytest

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import _page_has_dominant_raster, extract_pdf

HEADING = "An unusually long selectable heading for this page"
RECOGNIZED = "Synthetic scanned prose recovered from the raster tiles."


def _tiled_pdf(path: Path, *, pixels: int, placements: list[tuple[int, int]],
               substantial_text: bool = False) -> None:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, pixels, pixels), False)
    pix.clear_with(255)
    raster = pix.tobytes("png")
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=400)
        for x, y in placements:
            page.insert_image(fitz.Rect(x, y, x + 200, y + 200), stream=raster)
        page.insert_text((30, 60), HEADING, fontsize=10)
        if substantial_text:
            for index in range(5):
                page.insert_text(
                    (30, 90 + index * 24),
                    "Additional genuine selectable prose is present on this page.",
                    fontsize=9,
                )
        doc.save(path)


QUADRANTS = [(0, 0), (200, 0), (0, 200), (200, 200)]


@pytest.mark.parametrize(
    ("pixels", "placements", "expected"),
    [
        (300, QUADRANTS, True),
        (80, QUADRANTS, False),
        (300, [(0, 0)] * 4, False),
        (300, QUADRANTS[:2], False),
    ],
)
def test_raster_union_uses_visible_coverage_not_sum_of_tiles(
    tmp_path: Path, pixels: int, placements: list[tuple[int, int]], expected: bool,
) -> None:
    source = tmp_path / "tiled.pdf"
    _tiled_pdf(source, pixels=pixels, placements=placements)
    with fitz.open(source) as doc:
        assert _page_has_dominant_raster(doc[0]) is expected


@pytest.mark.parametrize(
    ("pixels", "placements", "substantial", "should_ocr"),
    [
        (300, QUADRANTS, False, True),
        (80, QUADRANTS, False, False),
        (300, [(0, 0)] * 4, False, False),
        (300, QUADRANTS, True, False),
    ],
)
def test_tiled_scan_auto_ocr_does_not_discard_valid_embedded_prose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    pixels: int, placements: list[tuple[int, int]],
    substantial: bool, should_ocr: bool,
) -> None:
    source = tmp_path / "tiled.pdf"
    _tiled_pdf(source, pixels=pixels, placements=placements, substantial_text=substantial)
    calls: list[bool] = []

    def fake_ocr(*args: object, **kwargs: object) -> list[dict]:
        calls.append(True)
        return [{
            "text": RECOGNIZED, "bbox": [30, 110, 350, 125],
            "font": "OCR", "size": 12.0,
        }]

    monkeypatch.setattr("pdf2audiobook.pdf._cached_ocr_lines", fake_ocr)
    result = extract_pdf(source, Pdf(ocr="auto"))
    assert bool(calls) is should_ocr
    if should_ocr:
        assert result.spans and result.spans[0].origin == "ocr"
        assert result.spans[0].text == RECOGNIZED
        assert any("sparse selectable text overlays" in w for w in result.warnings)
        assert any("automatic OCR did not reproduce short selectable text" in w
                   for w in result.warnings)
    else:
        assert result.spans and all(span.origin == "embedded" for span in result.spans)
        assert HEADING in " ".join(span.text for span in result.spans)
        assert not any("sparse selectable text overlays" in w for w in result.warnings)


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract unavailable")
def test_real_tesseract_recovers_prose_from_four_scanned_tiles(tmp_path: Path) -> None:
    """Actual engine integration with non-copyrighted text split across raster tiles."""
    source = tmp_path / "tiled-real-ocr.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=400)
        for index, (x, y) in enumerate(QUADRANTS):
            with fitz.open() as tile:
                tile_page = tile.new_page(width=200, height=200)
                if index == 0:
                    tile_page.insert_text((18, 110), "The scanner found prose.", fontsize=13)
                elif index == 2:
                    tile_page.insert_text((18, 110), "Another sentence survives.", fontsize=13)
                image = tile_page.get_pixmap(
                    matrix=fitz.Matrix(2, 2), alpha=False,
                ).tobytes("png")
                page.insert_image(fitz.Rect(x, y, x + 200, y + 200), stream=image)
        page.insert_text((30, 60), HEADING, fontsize=10)
        doc.save(source)

    embedded = extract_pdf(source, Pdf(ocr="never"))
    assert "scanner found prose" not in " ".join(s.text for s in embedded.spans).lower()

    result = extract_pdf(source, Pdf(ocr="auto", ocr_language="eng"))
    transcript = " ".join(s.text for s in result.spans).lower()
    assert "scanner found prose" in transcript
    assert "another sentence survives" in transcript
    assert result.spans and all(span.origin == "ocr" for span in result.spans)
    assert any("sparse selectable text overlays" in warning for warning in result.warnings)
