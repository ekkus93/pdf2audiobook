"""Pinned model destinations must be contained before creating directories."""

import hashlib

import pytest

from pdf2audiobook.errors import ConfigError
from pdf2audiobook.tts import catalog


@pytest.mark.parametrize("escape", ["traversal", "symlink"])
def test_fetch_rejects_escaping_parent_before_creating_directories(tmp_path, monkeypatch, escape):
    base = tmp_path / "cache"
    outside = tmp_path / "PRIVATE_OUTSIDE"
    if escape == "traversal":
        name = "../../PRIVATE_OUTSIDE/new/nested/weights.bin"
    else:
        base.mkdir()
        outside.mkdir()
        (base / "model").symlink_to(outside, target_is_directory=True)
        name = "new/nested/weights.bin"
    artifact = {
        "repo": catalog.MODEL_ID,
        "revision": "test",
        "name": name,
        "size": 4,
        "sha256": hashlib.sha256(b"data").hexdigest(),
    }
    monkeypatch.setitem(catalog.MANIFEST, "files", [artifact])

    def opener(*args, **kwargs):
        pytest.fail("unsafe path must be rejected before opening the network")

    with pytest.raises(ConfigError) as error:
        catalog.fetch_model(base, opener=opener)
    assert str(error.value) == "The model cache contains an unsafe directory"
    assert "PRIVATE" not in str(error.value)
    assert not (outside / "new").exists()
    if escape == "traversal":
        assert not outside.exists()
