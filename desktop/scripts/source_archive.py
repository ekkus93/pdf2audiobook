"""The source archive published next to the installers (self-contained app spec C9).

    uv run --no-project python desktop/scripts/source_archive.py ENGINE_DIR --output DIR [--cache DIR]

The installers are under the GNU AGPL 3.0 as a whole (PyMuPDF is AGPL-3.0; espeak-ng and others
are GPL), so each build's source goes with it. Writes `DIR/pdf2audiobook-<version>-source.tar`:

- `pdf2audiobook/`: this repository at the commit being built (`git archive HEAD`), with the
  build scripts, the pins and the lock files that fix every other component's version;
- `third-party/`: the source of every copyleft component (GPL, AGPL, LGPL, MPL) in the engine
  and the app, each checked by hash: FFmpeg and LAME from the pins, espeak-ng and
  espeakng-loader at their pinned commits, Python packages as the sdists in uv.lock, and Rust
  crates as the .crate files Cargo.lock names;
- `SOURCES.json`: each third-party file with its component, version, licence, origin and hash.

A copyleft component with no known source fails the build, so a new one cannot ship without
it. Tracked files with uncommitted changes fail it too, since the archive would not match.
Downloads go through the engine build's cache (--cache).
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path

import app_notices
import build_engine

ROOT = Path(__file__).resolve().parents[2]
COPYLEFT = re.compile(r"GPL|MPL|EPL|CDDL|EUPL|Mozilla|General Public")


def is_copyleft(licence: str) -> bool:
    return bool(COPYLEFT.search(licence))


def normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def sdists(lock: dict) -> dict[tuple[str, str], dict]:
    """(normalised name, version) to the sdist uv.lock records for it."""
    return {
        (normalise(package["name"]), package["version"]): package["sdist"]
        for package in lock["package"]
        if "sdist" in package and "url" in package["sdist"]
    }


def crate_checksums(lock: dict) -> dict[tuple[str, str], str]:
    return {
        (package["name"], package["version"]): package["checksum"]
        for package in lock["package"]
        if "checksum" in package
    }


def wanted(engine: Path, pins: dict) -> list[dict]:
    """Every copyleft component's source: name, version, licence, url and sha256."""
    listed = json.loads((engine / "share" / "licenses" / "components.json").read_text("utf-8"))
    python = sdists(tomllib.loads((ROOT / "uv.lock").read_text("utf-8")))
    ffmpeg = pins["ffmpeg"]
    pinned = {
        "ffmpeg": [ffmpeg], "lame": [ffmpeg["lame"]],
        "espeak-ng": [pins["sources"]["espeak-ng"]],
        "espeakng-loader": [pins["sources"]["espeakng-loader"], pins["sources"]["espeak-ng"]],
    }  # fmt: skip
    found: list[dict] = []
    missing = []
    for item in listed["components"]:
        if not is_copyleft(item["license"]):
            continue
        key = normalise(item["name"])
        base = {"component": item["name"], "version": item["version"], "license": item["license"]}
        if key in pinned:
            found += [{**base, "url": pin["url"], "sha256": pin["sha256"]} for pin in pinned[key]]
        elif (key, item["version"]) in python:
            sdist = python[(key, item["version"])]
            found.append({**base, "url": sdist["url"], "sha256": sdist["hash"].split(":", 1)[1]})
        else:
            missing.append(f"{item['name']} {item['version']}")
    crates = crate_checksums(
        tomllib.loads((ROOT / "desktop" / "src-tauri" / "Cargo.lock").read_text("utf-8"))
    )
    for item in app_notices.rust_components():
        if not is_copyleft(item["license"]):
            continue
        checksum = crates.get((item["name"], item["version"]))
        if checksum is None:
            missing.append(f"crate {item['name']} {item['version']}")
            continue
        found.append({
            "component": item["name"], "version": item["version"], "license": item["license"],
            "url": f"https://static.crates.io/crates/{item['name']}/"
                   f"{item['name']}-{item['version']}.crate",
            "sha256": checksum,
        })  # fmt: skip
    missing += [
        f"npm {item['name']} {item['version']}"
        for item in app_notices.npm_components()
        if is_copyleft(item["license"])
    ]
    if missing:
        sys.exit("No source pinned for these copyleft components: " + ", ".join(missing))
    # One file per download, however many components it serves.
    unique: dict[str, dict] = {}
    for entry in found:
        unique.setdefault(entry["sha256"], entry)
    return list(unique.values())


def file_name(entry: dict) -> str:
    name = entry["url"].rsplit("/", 1)[-1]
    if re.fullmatch(r"[0-9a-f]{40}\.tar\.gz", name):  # a GitHub archive of a commit
        name = f"{normalise(entry['component'])}-{name}"
    return name


def commit() -> tuple[str, int]:
    changed = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
                             check=True, text=True, capture_output=True).stdout  # fmt: skip
    if changed.strip():
        sys.exit("Tracked files have uncommitted changes; the archive would not match them")
    shown = subprocess.run(["git", "show", "-s", "--format=%H %ct", "HEAD"], cwd=ROOT,
                           check=True, text=True, capture_output=True).stdout.split()  # fmt: skip
    return shown[0], int(shown[1])


def build(engine: Path, output: Path, cache: Path) -> Path:
    pins = json.loads(build_engine.PINS.read_text(encoding="utf-8"))
    sha, when = commit()
    entries = wanted(engine, pins)
    version = app_notices.app_version()
    top = f"pdf2audiobook-{version}-source"
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"{top}.tar"

    def info(name: str, size: int) -> tarfile.TarInfo:
        member = tarfile.TarInfo(f"{top}/{name}")
        member.size, member.mtime, member.mode = size, when, 0o644
        return member

    with tempfile.TemporaryDirectory() as temp:
        repository = Path(temp) / "repository.tar"
        subprocess.run(["git", "archive", "--format=tar", f"--prefix={top}/pdf2audiobook/",
                        "-o", str(repository), "HEAD"], cwd=ROOT, check=True)  # fmt: skip
        with tarfile.open(archive, "w") as out:
            with tarfile.open(repository) as tree:
                for member in tree.getmembers():
                    out.addfile(member, tree.extractfile(member) if member.isfile() else None)
            sources = []
            for entry in entries:
                path = build_engine.fetch(entry["url"], entry["sha256"], cache)
                name = f"third-party/{file_name(entry)}"
                with path.open("rb") as stream:
                    out.addfile(info(name, path.stat().st_size), stream)
                sources.append({**entry, "file": name})
            readme = README.format(version=version, commit=sha).encode("utf-8")
            out.addfile(info("README.txt", len(readme)), io.BytesIO(readme))
            listing = (json.dumps({"commit": sha, "sources": sources}, indent=2) + "\n").encode()
            out.addfile(info("SOURCES.json", len(listing)), io.BytesIO(listing))
    return archive


README = """pdf2audiobook {version}: the complete source of the desktop app's installers

Commit {commit} of https://github.com/ekkus93/pdf2audiobook.

The AppImage and .deb built from this commit combine the app (Apache-2.0) with a built-in
engine that includes PyMuPDF (AGPL-3.0), espeak-ng, phonemizer and mutagen (GPL) and other
components under their own licences. As distributed, the app is under the GNU Affero General
Public License 3.0 (pdf2audiobook/desktop/licenses/AGPL-3.0.txt); each component keeps its own
licence, listed in the app's Settings > About.

pdf2audiobook/   this repository at that commit. desktop/README.md ("Building an installer")
                 describes the build; desktop/engine/pins.json, uv.lock, desktop/package-lock.json
                 and desktop/src-tauri/Cargo.lock fix every component's version and hash.
third-party/     the source of each copyleft component, as published by its project.
SOURCES.json     which component each file in third-party/ is, its licence, origin and sha256.
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("engine", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=ROOT / "tmp" / "engine-cache")
    args = parser.parse_args()
    archive = build(args.engine.resolve(), args.output.resolve(), args.cache.resolve())
    print(json.dumps({"archive": archive.name, "bytes": archive.stat().st_size}))


if __name__ == "__main__":
    main()
