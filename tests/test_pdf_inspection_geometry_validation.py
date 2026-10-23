"""PDF metadata inspection rejects invalid geometry without leaking parser text."""

import math
from pathlib import Path

import pytest

from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.pdf import inspect_pdf

PRIVATE = "SYNTHETIC_PRIVATE_INSPECTION_208"


@pytest.mark.parametrize(
    ("width", "height"),
    [
        (0, 842),
        (-1, 842),
        (math.nan, 842),
        (math.inf, 842),
        (595, 0),
        (595, math.inf),
        ("invalid", 842),
        (10**500, 842),
    ],
)
def test_inspect_pdf_rejects_unusable_page_sizes(monkeypatch, width, height) -> None:
    class Crop:
        pass

    class Page:
        rotation = 0
        cropbox = Crop()

    page = Page()
    page.cropbox.width = width
    page.cropbox.height = height

    class Document:
        metadata = {"title": "Synthetic", "author": None}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __len__(self):
            return 1

        def __iter__(self):
            yield page

        def get_toc(self):
            return []

        def get_page_labels(self):
            return []

    monkeypatch.setattr("pdf2audiobook.pdf._open", lambda *_args: Document())
    with pytest.raises(
        ExtractionError, match="Failed to inspect PDF metadata or page geometry"
    ) as raised:
        inspect_pdf(Path("synthetic.pdf"))
    assert PRIVATE not in str(raised.value)
    assert raised.value.__cause__ is None


def test_inspect_pdf_retains_valid_dimensions(monkeypatch) -> None:
    class Crop:
        width = 595
        height = 842.5

    class Page:
        rotation = 90
        cropbox = Crop()

        def get_label(self):
            return "xii"

        def get_text(self, _kind):
            return "Two words"

        def get_images(self, full=False):
            return [(1,)]

    class Document:
        metadata = {"title": "Synthetic", "author": None}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __len__(self):
            return 1

        def __iter__(self):
            yield Page()

        def get_toc(self):
            return []

        def get_page_labels(self):
            return []

    monkeypatch.setattr("pdf2audiobook.pdf._open", lambda *_args: Document())
    result = inspect_pdf(Path("synthetic.pdf"))
    assert result["page_sizes"] == [(595.0, 842.5)]
    assert result["page_rotations"] == [90]
    assert result["page_labels"] == ["xii"]
    assert result["embedded_text"] == {
        "pages_with_text": 1,
        "pages_without_text": 0,
        "image_only_pages": 0,
        "characters_per_page": [8],
        "images_per_page": [1],
    }


def test_inspect_reports_text_layers_and_labels_without_text(tmp_path) -> None:
    import pymupdf

    source = tmp_path / "layers.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "PRIVATE_BODY_TEXT here", fontsize=12)
    image_page = doc.new_page()
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), False)
    image_page.insert_image(pymupdf.Rect(72, 72, 144, 144), pixmap=pixmap)
    doc.new_page()
    doc.set_page_labels([{"startpage": 0, "prefix": "", "style": "r", "firstpagenum": 1}])
    doc.save(source)
    doc.close()
    result = inspect_pdf(source)
    assert result["page_labels"] == ["i", "ii", "iii"]
    summary = result["embedded_text"]
    assert summary["pages_with_text"] == 1
    assert summary["image_only_pages"] == 1
    assert summary["pages_without_text"] == 2
    assert summary["characters_per_page"][1:] == [0, 0]
    assert "PRIVATE_BODY_TEXT" not in repr(result)
