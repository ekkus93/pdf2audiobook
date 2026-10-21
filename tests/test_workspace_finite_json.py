"""Persistent JSON files reject nonfinite numbers without modifying valid artifacts."""

import json
import math

import pytest

from pdf2audiobook.workspace import write_json


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("existing", [False, True])
def test_nonfinite_json_is_rejected_without_publication(tmp_path, nonfinite, existing):
    path = tmp_path / "reports" / "usage.json"
    original = b'{"total": 1.25}\n'
    if existing:
        path.parent.mkdir()
        path.write_bytes(original)

    with pytest.raises(ValueError, match="Out of range float values"):
        write_json(path, {"private_note": "PRIVATE_BOOK_TEXT", "total": nonfinite})

    assert path.exists() is existing
    if existing:
        assert path.read_bytes() == original
        assert not list(path.parent.glob(".tmp-*"))
    else:
        assert not path.parent.exists()


def test_finite_json_still_roundtrips_and_stays_standard(tmp_path):
    path = tmp_path / "reports" / "usage.json"
    write_json(path, {"total": 1.25, "requests": 2, "items": [None, True, 0]})
    doc = json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda _: math.nan)
    assert doc["total"] == 1.25
    assert doc["requests"] == 2
    assert doc["items"] == [None, True, 0]
