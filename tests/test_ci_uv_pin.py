"""CI uses the uv release that wrote uv.lock, so `uv lock --check` is reproducible (R78)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ci_pins_uv_and_the_lockfile_revision_is_the_one_that_uv_writes():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    pinned = re.search(r'astral-sh/setup-uv@v6\s+with:\s+version: "(\d+\.\d+\.\d+)"', workflow)
    assert pinned is not None, "ci.yml must pin the uv version"
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert re.search(r"^revision = 3$", lock, re.MULTILINE)
    guide = (ROOT / "docs" / "MAINTAINER_GUIDE.md").read_text(encoding="utf-8")
    assert f"uv {pinned.group(1)}" in guide
