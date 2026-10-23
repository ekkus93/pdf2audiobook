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
