"""Untrusted PDF page dimensions must not escape domain-safe extraction."""

import math
from pathlib import Path

import pytest

from pdf2audiobook.config import Pdf
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.pdf import extract_pdf

PRIVATE = "SYNTHETIC_PRIVATE_GEOMETRY_MARKER_836"


@pytest.mark.parametrize(
    ("bad_width", "bad_height"),
    [
        (0, 842),
        (-10, 842),
        (math.nan, 842),
        (math.inf, 842),
        (595, 0),
        (595, -20),
        (595, math.nan),
        (595, math.inf),
        ("corrupt", 842),
    ],
)
def test_malformed_page_geometry_fails_before_text_extraction(
    monkeypatch, bad_width, bad_height
) -> None:
    class Crop:
        width = bad_width
        height = bad_height

    class Page:
        cropbox = Crop()

    class Document:
        metadata = {"title": "Synthetic", "author": "Test"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __len__(self):
            return 1

        def get_toc(self):
            return []

        def __iter__(self):
            yield Page()

    monkeypatch.setattr("pdf2audiobook.pdf._open", lambda *_args: Document())
    with pytest.raises(ExtractionError, match="PDF page geometry") as raised:
        extract_pdf(Path("synthetic.pdf"), Pdf(ocr="never"))
    assert PRIVATE not in str(raised.value)
    assert raised.value.__cause__ is None


def test_geometry_backend_exception_is_sanitized(monkeypatch):
    class Page:
        @property
        def cropbox(self):
            raise RuntimeError(f"untrusted parser diagnostic {PRIVATE}")

    class Document:
        metadata = {"title": "Synthetic", "author": None}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __len__(self):
            return 1

        def get_toc(self):
            return []

        def __iter__(self):
            yield Page()

    monkeypatch.setattr("pdf2audiobook.pdf._open", lambda *_args: Document())
    with pytest.raises(ExtractionError, match="cannot read PDF page geometry") as raised:
        extract_pdf(Path("synthetic.pdf"), Pdf(ocr="never"))
    assert PRIVATE not in str(raised.value)
    assert raised.value.__cause__ is None
