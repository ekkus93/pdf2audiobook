"""The desktop app's version matches the CLI's (Tauri spec D1.d, TODO TD2.03)."""

from __future__ import annotations

import json
import shutil
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "pyproject.toml",
    "desktop/package.json",
    "desktop/package-lock.json",
    "desktop/src-tauri/Cargo.toml",
    "desktop/src-tauri/tauri.conf.json",
)


def versions(root: Path) -> dict[str, str]:
    """Each file's declared version, keyed by its path relative to ``root``."""
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads((root / "desktop/package.json").read_text(encoding="utf-8"))
    lock = json.loads((root / "desktop/package-lock.json").read_text(encoding="utf-8"))
    cargo = tomllib.loads((root / "desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8"))
    tauri = json.loads((root / "desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    return {
        "pyproject.toml": pyproject["project"]["version"],
        "desktop/package.json": package["version"],
        "desktop/package-lock.json": lock["packages"][""]["version"],
        "desktop/src-tauri/Cargo.toml": cargo["package"]["version"],
        "desktop/src-tauri/tauri.conf.json": tauri["version"],
    }


def test_every_version_matches_pyproject() -> None:
    found = versions(ROOT)
    expected = found["pyproject.toml"]
    assert {path: version for path, version in found.items() if version != expected} == {}


@pytest.mark.parametrize("changed", FILES[1:])
def test_a_differing_version_is_detected(tmp_path: Path, changed: str) -> None:
    for name in FILES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    path = tmp_path / changed
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if changed.endswith("package-lock.json"):
            data["packages"][""]["version"] = "9.9.9"
        else:
            data["version"] = "9.9.9"
        path.write_text(json.dumps(data), encoding="utf-8")
    else:
        text = path.read_text(encoding="utf-8")
        current = versions(ROOT)[changed]
        path.write_text(
            text.replace(f'version = "{current}"', 'version = "9.9.9"', 1), encoding="utf-8"
        )

    found = versions(tmp_path)

    assert found[changed] == "9.9.9"
    assert found["pyproject.toml"] != found[changed]
