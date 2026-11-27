"""The desktop installers' licences: an AGPL-3.0 whole with its source (self-contained C9).

The installers combine the Apache-2.0 app with PyMuPDF (AGPL-3.0) and GPL components in the
built-in engine. `desktop/scripts/source_archive.py` collects every copyleft component's source
for the archive published next to them; these checks run its selection offline against the
real lock files and pins.
"""

from __future__ import annotations

import importlib
import json
import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "desktop" / "scripts"


@pytest.fixture(scope="module")
def source_archive() -> Iterator[ModuleType]:
    sys.path.insert(0, str(SCRIPTS))
    try:
        yield importlib.import_module("source_archive")
    finally:
        sys.path.remove(str(SCRIPTS))


@pytest.mark.parametrize(
    ("licence", "copyleft"),
    [
        ("Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License", True),
        ("GNU General Public License v3 or later (GPLv3+)", True),
        ("GPL-2.0-or-later", True),
        ("LGPL-2.1-or-later", True),
        ("MPL-2.0 AND MIT", True),
        ("MIT; includes espeak-ng (GPL-3.0-or-later, listed separately)", True),
        ("MIT OR Apache-2.0", False),
        ("BSD-3-Clause", False),
        ("PSF-2.0", False),
        ("Unicode-3.0", False),
    ],
)
def test_copyleft_licences_are_recognised(
    source_archive: ModuleType, licence: str, copyleft: bool
) -> None:
    assert source_archive.is_copyleft(licence) is copyleft


def test_the_copyleft_python_packages_have_sdists_in_the_lock(source_archive: ModuleType) -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    sdists = source_archive.sdists(lock)
    versions = {source_archive.normalise(p["name"]): p["version"] for p in lock["package"]}
    for name in ("pymupdf", "phonemizer", "mutagen", "certifi", "tqdm"):
        sdist = sdists[(name, versions[name])]
        assert sdist["url"].startswith("https://files.pythonhosted.org/")
        assert sdist["hash"].startswith("sha256:")


def test_espeak_sources_are_pinned_by_hash() -> None:
    pins = json.loads((ROOT / "desktop" / "engine" / "pins.json").read_text(encoding="utf-8"))
    commits = {
        "espeak-ng": pins["licenses"]["espeak-ng"]["commit"],
        "espeakng-loader": pins["licenses"]["espeakng-loader"]["commit"],
    }
    for name, commit in commits.items():
        source = pins["sources"][name]
        assert source["url"].endswith(f"/archive/{commit}.tar.gz")
        assert len(source["sha256"]) == 64


def test_github_commit_archives_are_named_after_their_project(source_archive: ModuleType) -> None:
    commit = "4870adfa25b1a32b4361592f1be8a40337c58d6c"
    entry = {"component": "espeak-ng", "url": f"https://github.com/x/y/archive/{commit}.tar.gz"}
    assert source_archive.file_name(entry) == f"espeak-ng-{commit}.tar.gz"
    crate = {
        "component": "selectors",
        "url": "https://static.crates.io/crates/selectors/selectors-0.38.0.crate",
    }
    assert source_archive.file_name(crate) == "selectors-0.38.0.crate"


def test_the_agpl_and_standard_licence_texts_are_in_the_repository() -> None:
    licences = ROOT / "desktop" / "licenses"
    assert (
        (licences / "AGPL-3.0.txt")
        .read_text(encoding="utf-8")
        .lstrip()
        .startswith("GNU AFFERO GENERAL PUBLIC LICENSE")
    )
    for name in ("MIT.txt", "BSD-3-Clause.txt", "MPL-2.0.txt"):
        assert (licences / name).stat().st_size > 500
