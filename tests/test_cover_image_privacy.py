"""Cover image failures do not disclose private paths or exception text."""

from pathlib import Path

import pytest

from pdf2audiobook.audio import read_cover_image
from pdf2audiobook.errors import ConfigError


def test_unreadable_private_cover_path_has_content_free_diagnostic(tmp_path: Path):
    private_path = tmp_path / "PRIVATE_COVER_PATH" / "cover.png"
    with pytest.raises(ConfigError) as raised:
        read_cover_image(private_path)
    assert str(raised.value) == "Cover image is unavailable; check the configured image file"
    assert "PRIVATE_COVER_PATH" not in str(raised.value)
    assert raised.value.__cause__ is None
