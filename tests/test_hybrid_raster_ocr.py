"""Hybrid scanned pages with short selectable overlays require OCR review."""
from __future__ import annotations

from pathlib import Path
import shutil

import fitz
import pytest

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import extract_pdf

HEADING = "An unusually long selectable heading for this page"
RECOGNIZED = "Scanned body prose recognized from the large raster page."


def _hybrid_page(path: Path, *, image_width: int, long_text: bool = False) -> None:
    # Use a real embedded raster, not a mocked image-coverage method.
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, image_width, image_width), False)
    pix.clear_with(255)
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=400)
        page.insert_image(page.rect, stream=pix.tobytes("png"))
        page.insert_text((30, 60), HEADING, fontsize=10)
        if long_text:
            for i in range(5):
                page.insert_text(
                    (30, 95 + i * 25),
                    "Additional genuine selectable paragraph text on this page.",
                    fontsize=9,
                )
        doc.save(path)


@pytest.mark.parametrize(
    ("mode", "image_width", "should_ocr"),
    [
        ("auto", 600, True),
        ("auto", 80, False),
        ("never", 600, False),
        ("always", 80, True),
    ],
)
def test_dominant_raster_with_selectable_heading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    image_width: int,
    should_ocr: bool,
) -> None:
    source = tmp_path / "hybrid.pdf"
    _hybrid_page(source, image_width=image_width)
    calls: list[bool] = []

    def fake_ocr(*args: object, **kwargs: object) -> list[dict]:
        calls.append(True)
        return [{
            "text": RECOGNIZED,
            "bbox": [30, 85, 350, 105],
            "font": "OCR",
            "size": 12.0,
        }]

    monkeypatch.setattr("pdf2audiobook.pdf._cached_ocr_lines", fake_ocr)
    extracted = extract_pdf(source, Pdf(ocr=mode))
    assert bool(calls) is should_ocr
    if should_ocr:
        assert len(extracted.spans) == 1
        assert extracted.spans[0].text == RECOGNIZED
        assert extracted.spans[0].origin == "ocr"
    else:
        assert extracted.spans[0].text == HEADING
        assert extracted.spans[0].origin == "embedded"
    hybrid_warning = any("sparse selectable text overlays" in w for w in extracted.warnings)
    missing_heading_warning = any(
        "automatic OCR did not reproduce short selectable text" in w
        for w in extracted.warnings
    )
    assert hybrid_warning is (mode == "auto" and image_width == 600)
    assert missing_heading_warning is (mode == "auto" and image_width == 600)


def test_dominant_raster_with_substantial_selectable_text_stays_embedded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "text-with-raster.pdf"
    _hybrid_page(source, image_width=600, long_text=True)

    def unexpected_ocr(*args: object, **kwargs: object) -> list[dict]:
        pytest.fail("substantial valid selectable text must not be replaced by OCR")

    monkeypatch.setattr("pdf2audiobook.pdf._cached_ocr_lines", unexpected_ocr)
    extracted = extract_pdf(source, Pdf(ocr="auto"))
    assert len(extracted.spans) >= 5
    assert all(span.origin == "embedded" for span in extracted.spans)
    assert not any("sparse selectable text overlays" in w for w in extracted.warnings)


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract CLI unavailable")
def test_real_tesseract_recovers_scanned_body_beneath_selectable_heading(
    tmp_path: Path,
) -> None:
    """Network-free actual OCR of raster prose, not just a recognition stub."""
    # Render synthetic, public-domain test prose into a raster image.
    with fitz.open() as raster_doc:
        page = raster_doc.new_page(width=400, height=400)
        page.insert_text(
            (35, 160), "The scanner captured this hidden body.", fontsize=17,
        )
        page.insert_text(
            (35, 195), "More prose belongs in the audiobook.", fontsize=17,
        )
        raster = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).tobytes("png")

    source = tmp_path / "hybrid-real-ocr.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=400)
        page.insert_image(page.rect, stream=raster)
        page.insert_text((35, 65), "Chapter Eleven A Very Long Heading", fontsize=12)
        doc.save(source)

    embedded = extract_pdf(source, Pdf(ocr="never"))
    assert "scanner captured" not in " ".join(s.text for s in embedded.spans).lower()

    recognized = extract_pdf(source, Pdf(ocr="auto", ocr_language="eng"))
    text = " ".join(s.text for s in recognized.spans).lower()
    assert "scanner captured" in text
    assert "belongs in the audiobook" in text
    assert recognized.spans and all(s.origin == "ocr" for s in recognized.spans)
    assert any("sparse selectable text overlays" in w for w in recognized.warnings)
