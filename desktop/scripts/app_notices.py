"""Licence notices for the desktop app itself: its Rust crates and its bundled npm packages.

    python3 desktop/scripts/app_notices.py OUTPUT_DIR

Writes `OUTPUT_DIR/components.json` in the engine's notice format (name, version, licence,
source, licence texts as paths relative to OUTPUT_DIR) and the texts under `texts/`, each
stored once. The first entry is the app as distributed: the installers combine Apache-2.0 code
with AGPL-3.0 and GPL components in the built-in engine, so the whole is under the GNU AGPL 3.0.

`package_engine.py` calls `write` and puts the folder at `/usr/lib/pdf2audiobook/licenses`, next
to the engine, where About reads it. The crates are those `cargo tree` links into the Linux
build (no build or development dependencies); the npm packages are the lockfile's non-development
ones, which Vite bundles into the frontend. A package that ships no licence text gets the standard
text of its licence from `desktop/licenses`; one with no standard text there fails the build.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "desktop"
CRATE = DESKTOP / "src-tauri"
LICENSES = DESKTOP / "licenses"
TARGET = "x86_64-unknown-linux-gnu"
REPOSITORY = "https://github.com/ekkus93/pdf2audiobook"
TEXT_NAMES = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE|UNLICENSE|COPYRIGHT)", re.IGNORECASE)
# Standard texts for a crate that ships none, by the first licence its manifest names.
STANDARD = {
    "MIT": LICENSES / "MIT.txt",
    "BSD-3-Clause": LICENSES / "BSD-3-Clause.txt",
    "MPL-2.0": LICENSES / "MPL-2.0.txt",
    "Apache-2.0": ROOT / "LICENSE",
}
STATEMENT = (
    "AGPL-3.0-only as distributed: the installers combine the app with its built-in engine, "
    "which includes PyMuPDF (AGPL-3.0) and GPL components. Its own source code is Apache-2.0."
)


def run(*command: str | Path, cwd: Path | None = None) -> str:
    return subprocess.run(
        [str(part) for part in command], check=True, text=True, capture_output=True, cwd=cwd
    ).stdout


def licence_files(folder: Path, licence: str, what: str) -> list[Path]:
    """A package's own licence texts, or the standard text of the first licence it names."""
    files = sorted(
        path
        for path in folder.iterdir()
        if path.is_file() and TEXT_NAMES.match(path.name) and path.suffix != ".spdx"
    )
    if files:
        return files
    first = re.split(r"[ /()]+", licence.strip(" ()"))[0]
    if first not in STANDARD:
        sys.exit(f"No licence text for {what}; add one to {LICENSES}")
    return [STANDARD[first]]


def linked_crates() -> set[tuple[str, str]]:
    """(name, version) of every crate linked into the Linux app, the app's own excluded."""
    tree = run("cargo", "tree", "--locked", "-e", "normal", "--target", TARGET, "--prefix",
               "none", "--format", "{p}", cwd=CRATE)  # fmt: skip
    crates = set()
    for line in tree.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].startswith("v"):
            crates.add((parts[0], parts[1][1:]))
    return crates


def rust_components() -> list[dict]:
    metadata = json.loads(run("cargo", "metadata", "--locked", "--format-version", "1",
                              "--filter-platform", TARGET, cwd=CRATE))  # fmt: skip
    root = metadata["resolve"]["root"]
    linked = linked_crates()
    found = []
    for package in metadata["packages"]:
        if package["id"] == root or (package["name"], package["version"]) not in linked:
            continue
        licence = package.get("license") or ""
        files = licence_files(Path(package["manifest_path"]).parent, licence,
                              f"the crate {package['name']}")  # fmt: skip
        source = package.get("repository") or f"https://crates.io/crates/{package['name']}"
        found.append({
            "name": package["name"], "version": package["version"], "license": licence,
            "source": f"{source} (crate {package['name']} {package['version']} on crates.io)",
            "paths": files,
        })  # fmt: skip
    return sorted(found, key=lambda item: (item["name"].lower(), item["version"]))


def npm_components() -> list[dict]:
    lock = json.loads((DESKTOP / "package-lock.json").read_text(encoding="utf-8"))
    found = []
    for key, entry in lock["packages"].items():
        if not key or entry.get("dev") or entry.get("devOptional"):
            continue
        folder = DESKTOP / key
        if not folder.is_dir():
            sys.exit("npm packages are missing; run `npm ci` in desktop/ first")
        manifest = json.loads((folder / "package.json").read_text(encoding="utf-8"))
        licence = entry.get("license") or manifest.get("license") or ""
        files = licence_files(folder, licence, f"the npm package {manifest['name']}")
        repository = manifest.get("repository")
        if isinstance(repository, dict):
            repository = repository.get("url")
        found.append({
            "name": manifest["name"], "version": manifest["version"],
            "license": licence,
            "source": f"{repository or entry.get('resolved')} (npm {manifest['name']} "
                      f"{manifest['version']})",
            "paths": files,
        })  # fmt: skip
    return sorted(found, key=lambda item: item["name"].lower())


def app_version() -> str:
    config = json.loads((CRATE / "tauri.conf.json").read_text(encoding="utf-8"))
    return str(config["version"])


def write(output: Path) -> int:
    """Write the app's notices to `output` (replaced if present); returns the component count."""
    if output.exists():
        shutil.rmtree(output)
    texts = output / "texts"
    texts.mkdir(parents=True)

    def store(path: Path) -> str:
        data = path.read_bytes()
        name = f"texts/{hashlib.sha256(data).hexdigest()[:16]}.txt"
        if not (output / name).exists():
            (output / name).write_bytes(data)
        return name

    shutil.copyfile(LICENSES / "AGPL-3.0.txt", output / "AGPL-3.0.txt")
    shutil.copyfile(ROOT / "LICENSE", output / "Apache-2.0.txt")
    components = [{
        "name": "pdf2audiobook (this app)", "version": app_version(), "license": STATEMENT,
        "source": f"{REPOSITORY}; the complete source of each build, its copyleft components "
                  "included, is the source archive published next to the installers",
        "files": ["AGPL-3.0.txt", "Apache-2.0.txt"],
    }]  # fmt: skip
    for item in rust_components() + npm_components():
        paths = item.pop("paths")
        components.append({**item, "files": [store(path) for path in paths]})
    (output / "components.json").write_text(
        json.dumps({"components": components}, indent=2) + "\n", encoding="utf-8"
    )
    return len(components)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(write(args.output.resolve()))


if __name__ == "__main__":
    main()
