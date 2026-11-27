"""Put the built engine into the AppImage and .deb that `tauri build` made (self-contained SC7).

    python3 desktop/scripts/package_engine.py ENGINE_DIR [--bundle DIR] [--appimagetool PATH]

Tauri's AppImage step runs linuxdeploy over every program file in the image and rewrites
their library search paths, which would change the engine's Python packages. So the app is
bundled without the engine, and this script adds the engine afterwards, unchanged: it unpacks
each AppImage, copies the engine to `usr/lib/pdf2audiobook/engine` (where the app's resource
folder is) and packs it again with the same runtime; each .deb gets the engine at
`/usr/lib/pdf2audiobook/engine`, with its control and checksum files updated. Both also get the
app's own licence notices (`app_notices.py`) at `usr/lib/pdf2audiobook/licenses`. It prints the
sizes as JSON, for the ledger, and fails if a package is over the size budget (spec C8).

appimagetool comes from the linuxdeploy AppImage plugin that `tauri build` downloads, unless
--appimagetool names one. Nothing is downloaded here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import app_notices

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "desktop" / "src-tauri" / "target" / "release" / "bundle"
# Tauri's resource folder on Linux: /usr/lib/<productName>, also inside the AppImage.
RESOURCES = Path("usr") / "lib" / "pdf2audiobook"
TARGET = RESOURCES / "engine"
NOTICES = RESOURCES / "licenses"
PLUGIN = Path.home() / ".cache" / "tauri" / "linuxdeploy-plugin-appimage.AppImage"
MARKER = "pdf2audiobook-bundle.json"
# Spec C8: the compressed installer and the installed app, before add-ons.
BUDGET = {"compressed": 400_000_000, "installed": 1_000_000_000}


def run(*command: str | Path, **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(part) for part in command], check=True, text=True, **kwargs)


def tree_size(folder: Path) -> int:
    """Bytes in regular files under `folder`, symbolic links not followed."""
    return sum(
        path.lstat().st_size
        for path in folder.rglob("*")
        if path.is_file() and not path.is_symlink()
    )


def appimagetool(given: Path | None, work: Path) -> Path:
    if given is not None:
        return given
    if not PLUGIN.is_file():
        sys.exit(
            "No appimagetool: run `tauri build --bundles appimage` first, or pass --appimagetool"
        )
    run(PLUGIN, "--appimage-extract", cwd=work, capture_output=True)
    return work / "squashfs-root" / "usr" / "bin" / "appimagetool"


def add_payload(root: Path, engine: Path, notices: Path, name: str) -> None:
    for target in (TARGET, NOTICES):
        if (root / target).exists():
            sys.exit(f"{name} already has {target.name}; build it again without them")
    shutil.copytree(engine, root / TARGET, symlinks=True)
    shutil.copytree(notices, root / NOTICES)


def package_appimage(image: Path, engine: Path, notices: Path, tool: Path, work: Path) -> None:
    folder = work / "image"
    folder.mkdir()
    offset = int(run(image, "--appimage-offset", capture_output=True).stdout.strip())
    run(image, "--appimage-extract", cwd=folder, capture_output=True)
    root = folder / "squashfs-root"
    add_payload(root, engine, notices, image.name)
    runtime = work / "runtime"
    with image.open("rb") as source:
        runtime.write_bytes(source.read(offset))
    packed = work / image.name
    # The AppImage runtime reads only zstd; the strongest level and 1 MiB blocks save about
    # 15 MB over the defaults (spec C8).
    run(tool, "--no-appstream", "--comp", "zstd", "--mksquashfs-opt", "-b",
        "--mksquashfs-opt", "1M", "--mksquashfs-opt", "-Xcompression-level",
        "--mksquashfs-opt", "19", "--runtime-file", runtime, root, packed,
        env={**os.environ, "ARCH": "x86_64"}, capture_output=True)  # fmt: skip
    packed.chmod(0o755)
    os.replace(packed, image)


def package_deb(deb: Path, engine: Path, notices: Path, work: Path) -> int:
    root = work / "deb"
    run("dpkg-deb", "-R", deb, root)
    add_payload(root, engine, notices, deb.name)
    sums = root / "DEBIAN" / "md5sums"
    with sums.open("a", encoding="utf-8") as stream:
        added = [*(root / TARGET).rglob("*"), *(root / NOTICES).rglob("*")]
        for path in sorted(added):
            if path.is_file() and not path.is_symlink():
                digest = hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()
                stream.write(f"{digest}  {path.relative_to(root)}\n")
    installed = tree_size(root) - tree_size(root / "DEBIAN")
    control = root / "DEBIAN" / "control"
    lines = [
        f"Installed-Size: {-(-installed // 1024)}" if line.startswith("Installed-Size:") else line
        for line in control.read_text(encoding="utf-8").splitlines()
    ]
    control.write_text("\n".join(lines) + "\n", encoding="utf-8")
    packed = work / deb.name
    # xz: every dpkg can read it.
    run("dpkg-deb", "--root-owner-group", "-Zxz", "-b", root, packed, capture_output=True)
    os.replace(packed, deb)
    return installed


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("engine", type=Path)
    parser.add_argument("--bundle", type=Path, default=BUNDLE)
    parser.add_argument("--appimagetool", type=Path)
    args = parser.parse_args()
    engine = args.engine.resolve()
    if not (engine / MARKER).is_file():
        sys.exit("Not a built engine; run desktop/scripts/build_engine.py first")
    if json.loads((engine / MARKER).read_text(encoding="utf-8")).get("ffmpeg") is None:
        sys.exit("This engine was built --without-ffmpeg, for development only")
    images = sorted((args.bundle / "appimage").glob("*.AppImage"))
    debs = sorted((args.bundle / "deb").glob("*.deb"))
    if not images and not debs:
        sys.exit("No AppImage or .deb to add the engine to; run `tauri build` first")
    sizes: dict[str, dict[str, int]] = {"engine": {"installed": tree_size(engine)}}
    scratch = os.environ.get("TMPDIR")
    with tempfile.TemporaryDirectory(dir=scratch) as temp:
        notices = Path(temp) / "licenses"
        app_notices.write(notices)
        for image in images:
            with tempfile.TemporaryDirectory(dir=scratch) as work:
                tool = appimagetool(args.appimagetool, Path(work))
                package_appimage(image, engine, notices, tool, Path(work))
            sizes["appimage"] = {"compressed": image.stat().st_size}
        for deb in debs:
            with tempfile.TemporaryDirectory(dir=scratch) as work:
                installed = package_deb(deb, engine, notices, Path(work))
            sizes["deb"] = {"compressed": deb.stat().st_size, "installed": installed}
    print(json.dumps(sizes, indent=2))
    over = [
        f"{kind} {what} is {value / 1e6:.0f} MB, over {BUDGET[what] / 1e6:.0f} MB"
        for kind, measured in sizes.items()
        for what, value in measured.items()
        if kind != "engine" and value > BUDGET[what]
    ]
    if over:
        sys.exit("Over the size budget (spec C8; going over needs a dated note there): " + "; ".join(over))


if __name__ == "__main__":
    main()
