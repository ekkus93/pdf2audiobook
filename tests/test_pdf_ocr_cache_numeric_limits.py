"""Corrupted OCR cache numbers must fail closed without raising OverflowError."""

import json

import fitz
import pytest

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import _cached_ocr_lines, _valid_cached_lines
from pdf2audiobook.workspace import fingerprint


def entry(*, bbox=None, size=12):
    return {
        "text": "Synthetic OCR text.",
        "bbox": [10, 20, 230, 35] if bbox is None else bbox,
        "font": "TestFont",
        "size": size,
    }


@pytest.mark.parametrize(
    "bbox",
    [
        [10**400, 20, 10**400 + 50, 35],
        [10, 20, 10**400, 35],
        [10, 20, float("nan"), 35],
        [10, 20, float("inf"), 35],
        [10, 20, -float("inf"), 35],
    ],
)
def test_oversized_or_nonfinite_cached_bbox_is_rejected(bbox):
    assert _valid_cached_lines({"schema_version": 1, "lines": [entry(bbox=bbox)]}) is None


@pytest.mark.parametrize("size", [10**400, float("nan"), float("inf"), -1, True])
def test_oversized_or_nonfinite_cached_font_size_is_rejected(size):
    assert _valid_cached_lines({"schema_version": 1, "lines": [entry(size=size)]}) is None


def test_invalid_oversized_cache_refreshes_with_verified_ocr(tmp_path, monkeypatch):
    from pdf2audiobook import pdf

    settings = Pdf(ocr="auto")
    monkeypatch.setattr(pdf, "_ocr_engine_version", lambda: "synthetic-test-version")
    valid = entry()
    calls = []

    def fresh_ocr(page, config):
        calls.append(True)
        return [valid]

    monkeypatch.setattr(pdf, "_ocr_page_lines", fresh_ocr)
    key = fingerprint(
        "ocr-lines-v1",
        "a" * 64,
        0,
        settings.ocr_language,
        settings.ocr_dpi,
        str(fitz.VersionBind),
        "synthetic-test-version",
        0,
    )
    target = tmp_path / f"{key}.json"
    target.write_text(
        json.dumps({"schema_version": 1, "lines": [entry(bbox=[10**400, 20, 230, 35])]}),
        encoding="utf-8",
    )

    class Page:
        rotation = 0

    result = _cached_ocr_lines(
        Page(),
        settings,
        cache_dir=tmp_path,
        input_sha256="a" * 64,
        page_index=0,
    )
    assert result == [valid]
    assert len(calls) == 1
    assert json.loads(target.read_text(encoding="utf-8"))["lines"] == [valid]
    assert _cached_ocr_lines(
        Page(),
        settings,
        cache_dir=tmp_path,
        input_sha256="a" * 64,
        page_index=0,
    ) == [valid]
    assert len(calls) == 1
