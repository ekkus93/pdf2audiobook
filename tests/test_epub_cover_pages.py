"""An EPUB cover on a page-sized background is not a damaged source (E5)."""

from pathlib import Path

import pymupdf
import pytest
from epub_book import write_novel_epub

from pdf2audiobook.config import Settings
from pdf2audiobook.pdf import _background_only
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.workspace import read_manifest


def _analyze(source: Path, tmp_path: Path):
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.llm.enabled = False
    settings.chapters.allow_single_chapter = True
    return read_manifest(analyze_book(source, settings))


def test_a_cover_image_on_a_page_background_does_not_flag_damage(tmp_path: Path) -> None:
    manifest = _analyze(write_novel_epub(tmp_path / "n.epub", chapters=6), tmp_path)
    assert "damaged_source" not in manifest.review_required
    assert any(w.startswith("Page 1: no readable text (image-only page") for w in manifest.warnings)
    assert any(w.startswith("Page 1: embedded image detected") for w in manifest.warnings)


def test_an_epub_without_a_cover_has_no_damage_flag(tmp_path: Path) -> None:
    source = write_novel_epub(tmp_path / "n.epub", chapters=6, cover=False)
    assert "damaged_source" not in _analyze(source, tmp_path).review_required


def test_real_vector_art_with_no_text_still_flags_damage(tmp_path: Path) -> None:
    source = write_novel_epub(tmp_path / "n.epub", chapters=6, art_page=True)
    manifest = _analyze(source, tmp_path)
    assert "damaged_source" in manifest.review_required
    assert any("drawings present but not text-like" in w for w in manifest.warnings)


def test_a_pdf_page_like_the_epub_cover_still_flags_damage(tmp_path: Path) -> None:
    png = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), False)
    png.set_rect(png.irect, (10, 80, 150))
    source = tmp_path / "scan.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Chapter 1", fontsize=24)
    page.insert_text((72, 120), "Plain words.", fontsize=11)
    cover = document.new_page()
    cover.draw_rect(cover.rect, color=None, fill=(1, 1, 1))
    cover.insert_image(pymupdf.Rect(50, 50, 200, 200), stream=png.tobytes("png"))
    document.save(source)
    document.close()
    assert "damaged_source" in _analyze(source, tmp_path).review_required


class _Rect:
    def __init__(self, width: float, height: float) -> None:
        self.width, self.height = width, height


@pytest.mark.parametrize(
    ("drawings", "expected"),
    [
        ([{"rect": _Rect(400, 600), "fill": (1, 1, 1), "color": None}], True),
        ([{"rect": _Rect(390, 590), "fill": (1, 1, 1), "color": None}], True),  # >= 95%
        ([{"rect": _Rect(300, 600), "fill": (1, 1, 1), "color": None}], False),  # 75%
        ([{"rect": _Rect(400, 600), "fill": (1, 1, 1), "color": (0, 0, 0)}], False),  # stroked
        ([{"rect": _Rect(400, 600), "fill": None, "color": None}], False),  # no fill
        (
            [
                {"rect": _Rect(400, 600), "fill": (1, 1, 1), "color": None},
                {"rect": _Rect(10, 10), "fill": (0, 0, 0), "color": None},
            ],
            False,
        ),
        ([], False),
        ([{"rect": None, "fill": (1, 1, 1), "color": None}], False),
    ],
)
def test_background_only_requires_every_drawing_to_be_a_page_sized_fill(drawings, expected) -> None:
    assert _background_only(_Rect(400, 600), drawings) is expected
