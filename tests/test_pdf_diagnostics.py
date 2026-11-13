"""Test preservation of printed page labels and Tesseract language diagnostics."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from pdf2audiobook import pdf_ocr
from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import (
    extract_pdf,
    missing_ocr_languages,
    tesseract_languages,
)
from pdf2audiobook.pdf_layout import _PageVisuals


def test_page_labels_in_provenance(tmp_path: Path):
    source = tmp_path / "labels.pdf"
    document = fitz.open()
    document.new_page().insert_text((80, 120), "A page with an introduction.")
    document.new_page().insert_text((80, 120), "Next page of the book.")
    document.set_page_labels([{"startpage": 0, "style": "r", "firstpagenum": 1}])
    document.save(source)
    document.close()

    extracted = extract_pdf(source, Pdf(ocr="never"))
    assert [span.page_label for span in extracted.spans] == ["i", "ii"]


def test_tesseract_languages_and_missing_language(monkeypatch):
    monkeypatch.setattr("pdf2audiobook.pdf_ocr.shutil.which", lambda name: "/bin/tesseract")
    fake = SimpleNamespace(
        returncode=0,
        stdout="List of available languages in /usr/share/tessdata (2):\neng\nfra\n",
        stderr="",
    )
    monkeypatch.setattr("pdf2audiobook.pdf_ocr.subprocess.run", lambda *a, **k: fake)
    assert tesseract_languages() == ["eng", "fra"]
    assert missing_ocr_languages("eng+spa", ["eng", "fra"]) == ["spa"]
    assert missing_ocr_languages("eng", None) == ["eng"]


# --- OCR error branches and heuristic early returns (test coverage spec T6.c) --


def _tesseract(monkeypatch, *, installed=True, run=None):
    """Replace pdf_ocr's view of the Tesseract CLI without touching global modules."""
    monkeypatch.setattr(
        pdf_ocr, "shutil", SimpleNamespace(which=lambda _n: "/bin/tesseract" if installed else None)
    )
    monkeypatch.setattr(
        pdf_ocr,
        "subprocess",
        SimpleNamespace(run=run, TimeoutExpired=subprocess.TimeoutExpired),
    )


def _raising(error):
    def run(*_args, **_kwargs):
        raise error

    return run


def _returning(returncode, stdout="", stderr=""):
    return lambda *_a, **_k: SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture
def fresh_engine_version():
    pdf_ocr._ocr_engine_version.cache_clear()
    yield
    pdf_ocr._ocr_engine_version.cache_clear()


@pytest.mark.parametrize(
    ("installed", "run", "expected"),
    [
        (False, None, "tesseract-cli-unavailable"),
        (True, _raising(OSError(13, "Permission denied")), "tesseract-cli-unknown"),
        (True, _raising(subprocess.TimeoutExpired("tesseract", 10)), "tesseract-cli-unknown"),
        (True, _returning(1, stdout="tesseract 5.3.0"), "tesseract-cli-unknown"),
    ],
    ids=["not-installed", "os-error", "timeout", "nonzero-exit"],
)
def test_ocr_engine_version_falls_back_without_failing(
    monkeypatch, fresh_engine_version, installed, run, expected
):
    """T6.c: a missing or broken Tesseract CLI gives a fixed cache identity."""
    _tesseract(monkeypatch, installed=installed, run=run)

    assert pdf_ocr._ocr_engine_version() == expected


@pytest.mark.parametrize(
    ("installed", "run", "expected"),
    [
        (False, None, None),
        (True, _raising(OSError(13, "Permission denied")), []),
        (True, _raising(subprocess.TimeoutExpired("tesseract", 10)), []),
        (True, _returning(1, stdout="eng\n"), []),
    ],
    ids=["not-installed", "os-error", "timeout", "nonzero-exit"],
)
def test_language_listing_failures_are_reported_as_none_or_empty(
    monkeypatch, installed, run, expected
):
    """T6.c: None means no Tesseract; an empty list means it could not list languages."""
    _tesseract(monkeypatch, installed=installed, run=run)

    assert tesseract_languages() == expected


def test_ocr_cache_requires_the_source_hash(tmp_path):
    """T6.c: caching without the source digest is refused before any OCR runs."""
    with pytest.raises(ValueError, match="^OCR caching requires the source PDF SHA-256$"):
        pdf_ocr._cached_ocr_lines(None, Pdf(), cache_dir=tmp_path, input_sha256=None, page_index=0)

    assert list(tmp_path.iterdir()) == []


_PAGE = SimpleNamespace(cropbox=SimpleNamespace(width=600, height=800))


def _raster(*images, page=_PAGE):
    visuals = _PageVisuals(
        images=list(images), drawings=[], image_count=len(images), drawing_count=0
    )
    return pdf_ocr._page_has_dominant_raster(page, visuals)


def _image(bbox, pixels=2000):
    return {"width": pixels, "height": pixels, "bbox": bbox}


def test_dominant_raster_counts_separate_images_and_gaps():
    """T6.c: two images with a gap between them still cover most of the page."""
    # Stacked, with a vertical gap: 600 x (300 + 400) of 600 x 800.
    assert _raster(_image((0, 0, 600, 300)), _image((0, 400, 600, 800))) is True
    # Side by side, with an empty strip between them: (200 + 200) x 800 of 600 x 800.
    assert _raster(_image((0, 0, 200, 800)), _image((400, 0, 600, 800))) is True
    # A gap is not coverage: 600 x (200 + 200) of 600 x 800 is only half the page.
    assert _raster(_image((0, 0, 600, 200)), _image((0, 600, 600, 800))) is False


@pytest.mark.parametrize(
    "bad",
    [_image((100, 0, 100, 800)), _image((0, 400, 600, 400))],
    ids=["zero-width", "zero-height"],
)
def test_degenerate_image_is_skipped_not_fatal(bad):
    """T6.c: a zero-size image is skipped; the real full-page scan still counts."""
    assert _raster(_image((0, 0, 600, 800)), bad) is True


@pytest.mark.parametrize(
    ("images", "page"),
    [
        ([_image((0, 0, 600, 800))], SimpleNamespace(cropbox=SimpleNamespace(width=0, height=800))),
        ([_image((0, 0, 600, 800))] * 257, _PAGE),
        ([_image((float("nan"), 0, 600, 800))], _PAGE),
        ([_image((100, 0, 100, 800))], _PAGE),
        ([_image((0, 0, 600, 800), pixels=300)], _PAGE),
        ([_image((700, 900, 1300, 1700))], _PAGE),
        ([{"width": 2000, "height": 2000}], _PAGE),
    ],
    ids=[
        "zero-area-page",
        "too-many-images",
        "non-finite-bounds",
        "zero-width-bounds",
        "low-pixel-density",
        "off-the-page",
        "missing-bbox",
    ],
)
def test_dominant_raster_rejects_implausible_or_malformed_images(images, page):
    """T6.c: none of these is evidence of a scanned page."""
    assert _raster(*images, page=page) is False


class _Rect(SimpleNamespace):
    pass


def _vector(drawings, *, width=600, height=800):
    page = SimpleNamespace(cropbox=SimpleNamespace(width=width, height=height))
    count = len(drawings) if hasattr(drawings, "__len__") else 0
    visuals = _PageVisuals(images=[], drawings=drawings, image_count=0, drawing_count=count)
    return pdf_ocr._page_has_dense_vector_art(page, visuals)


_GLYPH = {"rect": _Rect(width=8, height=10), "fill": (0, 0, 0)}


@pytest.mark.parametrize(
    ("drawings", "size", "expected"),
    [
        ([_GLYPH] * 40, (600, 800), True),
        ([_GLYPH] * 40 + [{"fill": (0, 0, 0)}], (600, 800), True),
        ([_GLYPH] * 100, (0, 800), False),
        (
            [_GLYPH] * 39 + [{"rect": _Rect(width="wide", height=1), "fill": None}],
            (600, 800),
            False,
        ),
    ],
    ids=["forty-glyphs", "path-without-rect", "zero-width-page", "malformed-rect"],
)
def test_dense_vector_art_detection_guards(drawings, size, expected):
    """T6.c: rect-less paths are skipped; invalid pages or rects never trigger OCR."""
    assert _vector(drawings, width=size[0], height=size[1]) is expected


def test_dense_vector_art_needs_a_drawing_list():
    """T6.c: drawings that are not a list or tuple are not evidence, even if iterable."""
    assert _vector(iter([_GLYPH] * 40)) is False
    assert _vector("not a list") is False
