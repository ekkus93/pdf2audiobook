"""The desktop app stays out of the Python packages and Python checks (Tauri TODO TD2.02)."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sdist_prunes_the_desktop_folder() -> None:
    lines = (ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()
    assert "prune desktop" in lines


def test_ruff_and_mypy_do_not_check_the_desktop_folder() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "desktop" in config["tool"]["ruff"]["extend-exclude"]
    assert not [path for path in config["tool"]["mypy"]["files"] if "desktop" in path]
    assert config["tool"]["setuptools"]["packages"]["find"]["where"] == ["src"]


def test_ci_fails_if_a_package_contains_the_desktop_folder() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert 'grep -q "desktop/"' in workflow and 'grep -q "/desktop/"' in workflow
    assert "desktop/ was packaged into the wheel or sdist" in workflow
