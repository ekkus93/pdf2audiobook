"""Build the desktop app's bundled engine (self-contained app spec SC1, SC4).

    uv run --no-project python desktop/scripts/build_engine.py OUTPUT_DIR [--cache DIR]

Produces OUTPUT_DIR/engine: a relocatable CPython from uv, pdf2audiobook and its locked
core dependencies, the Kitten 0.8 ONNX voice path without PyTorch, FFmpeg, English OCR data
and the default voice model. Everything comes from uv.lock or desktop/engine/pins.json and is
checked by hash. Downloads are kept in --cache and reused when their hashes match.

--without-ffmpeg builds without FFmpeg, for local development only; the marker records it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PINS = ROOT / "desktop" / "engine" / "pins.json"
MARKER = "pdf2audiobook-bundle.json"
LAUNCHER = """#!/bin/sh
# Start the bundled engine through its own interpreter, wherever the app is installed.
here=$(dirname "$(readlink -f "$0")")
exec "$here/python3" -m pdf2audiobook "$@"
"""


def run(*command: str | Path, **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(part) for part in command], check=True, text=True, **kwargs)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(url: str, expected: str, cache: Path) -> Path:
    """A pinned download, from the cache when its hash already matches."""
    target = cache / expected
    if target.is_file() and sha256(target) == expected:
        return target
    cache.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".partial")
    with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as stream:
        shutil.copyfileobj(response, stream)
    if sha256(partial) != expected:
        partial.unlink()
        sys.exit(f"Hash mismatch for a pinned download; check desktop/engine/pins.json: {url}")
    partial.replace(target)
    return target


def locked_closure(names: set[str]) -> set[str]:
    """The packages `names` depend on in uv.lock, transitively."""
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    graph = {
        package["name"]: {dep["name"] for dep in package.get("dependencies", [])}
        for package in lock["package"]
    }
    found, pending = set(), list(names)
    while pending:
        name = pending.pop()
        if name not in found:
            found.add(name)
            pending.extend(graph.get(name, ()))
    return found


def requirement_blocks(text: str) -> dict[str, list[str]]:
    """`uv export` output split into hashed requirements by package name.

    A package can appear more than once, with different versions for different Python
    versions (environment markers); every entry is kept and pip picks the matching one.
    """
    blocks: dict[str, list[str]] = {}
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        if not line.startswith(" "):
            name = re.split(r"[=<>; \[]", line, maxsplit=1)[0].lower().replace("_", "-")
            blocks.setdefault(name, []).append(line)
        else:
            blocks[name][-1] += "\n" + line
    return blocks


def install_packages(python: Path, work: Path, pins: dict) -> None:
    export = run(
        "uv", "export", "--locked", "--no-dev", "--no-emit-project", "--extra", "kitten",
        "--format", "requirements-txt", cwd=ROOT, capture_output=True,
    ).stdout  # fmt: skip
    blocks = requirement_blocks(export)
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    project = next(package for package in lock["package"] if package["name"] == "pdf2audiobook")
    core = {dep["name"] for dep in project.get("dependencies", [])}
    onnx = set(pins["packages"]["kittenml_onnx"])
    # kittenml itself is installed without its dependencies; its ONNX imports are listed.
    wanted = locked_closure(core) | locked_closure(onnx - {"kittenml"}) | {"kittenml"}
    missing = sorted(wanted - blocks.keys())
    if missing:
        sys.exit(f"Not in the locked export: {', '.join(missing)}")
    requirements = work / "requirements.txt"
    requirements.write_text("\n".join(entry for name in sorted(wanted) for entry in blocks[name]) + "\n")
    run("uv", "pip", "install", "--python", python, "--break-system-packages",
        "--require-hashes", "--no-deps", "-r", requirements)  # fmt: skip
    run("uv", "build", "--wheel", "--out-dir", work / "wheel", cwd=ROOT, capture_output=True)
    wheel = next((work / "wheel").glob("pdf2audiobook-*.whl"))
    run("uv", "pip", "install", "--python", python, "--break-system-packages", "--no-deps", wheel)


def build(output: Path, cache: Path, with_ffmpeg: bool) -> None:
    pins = json.loads(PINS.read_text(encoding="utf-8"))
    engine = output / "engine"
    if engine.exists():
        shutil.rmtree(engine)
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as temp:
        work = Path(temp)
        run("uv", "python", "install", pins["python"], "--install-dir", work / "python",
            capture_output=True)  # fmt: skip
        source = next(p for p in (work / "python").iterdir() if p.is_dir() and not p.is_symlink()
                      and p.name.startswith(f"cpython-{pins['python']}-"))  # fmt: skip
        shutil.copytree(source, engine, symlinks=True)
        python = engine / "bin" / "python3"
        install_packages(python, work, pins)

    # Console scripts carry the build path in their shebang; the launcher replaces them.
    for script in (engine / "bin").iterdir():
        if script.is_file() and not script.name.startswith("python"):
            first = script.read_bytes()[:256]
            if first.startswith(b"#!") and str(engine).encode() in first:
                script.unlink()
    # Parts of CPython the engine never uses: pip, the Tk GUI toolkit, IDLE and build headers.
    unused = [
        "include", "bin/pip*", "bin/idle*", "bin/2to3*", "bin/pydoc*", "bin/python*-config",
        "lib/tcl*", "lib/tk*", "lib/itcl*", "lib/thread*", "lib/python3*/site-packages/pip*",
        "lib/python3*/idlelib", "lib/python3*/tkinter", "lib/python3*/turtledemo",
        "lib/python3*/ensurepip", "lib/python3*/lib2to3", "lib/python3*/lib-dynload/_tkinter*",
    ]  # fmt: skip
    for pattern in unused:
        for path in engine.glob(pattern):
            shutil.rmtree(path) if path.is_dir() and not path.is_symlink() else path.unlink()
    launcher = engine / "bin" / "pdf2audiobook"
    launcher.write_text(LAUNCHER, encoding="utf-8")
    launcher.chmod(0o755)

    share = engine / "share"
    licenses = share / "licenses"
    tessdata = share / "tessdata"
    tessdata.mkdir(parents=True)
    for item in pins["tessdata"]:
        shutil.copyfile(fetch(item["url"], item["sha256"], cache),
                        tessdata / f"{item['language']}.traineddata")  # fmt: skip
    for model in pins["models"]:
        folder = share / "pdf2audiobook" / "models" / model["repo"].rsplit("/", 1)[-1]
        folder.mkdir(parents=True)
        base = f"https://huggingface.co/{model['repo']}/resolve/{model['revision']}"
        for name, digest in model["files"].items():
            shutil.copyfile(fetch(f"{base}/{name}", digest, cache), folder / name)

    if with_ffmpeg:
        item = pins["ffmpeg"]
        archive = fetch(item["url"], item["sha256"], cache)
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                parts = Path(member.name).parts
                if member.isfile() and parts[-2:] == ("bin", "ffmpeg"):
                    target = engine / "bin" / "ffmpeg"
                elif member.isfile() and parts[-1] == "LICENSE.txt":
                    target = licenses / "ffmpeg" / "LICENSE.txt"
                else:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as stream, target.open("wb") as out:  # type: ignore[union-attr]
                    shutil.copyfileobj(stream, out)
                target.chmod(0o755 if target.name == "ffmpeg" else 0o644)

    # Precompiled bytecode: an AppImage is read-only, so Python cannot cache it at run time.
    run(python, "-m", "compileall", "-q", "-j", "0", engine / "lib", capture_output=True)
    version = run(python, "-m", "pdf2audiobook", "--version", capture_output=True).stdout.strip()
    (engine / MARKER).write_text(json.dumps({
        "version": version,
        "python": pins["python"],
        "ffmpeg": pins["ffmpeg"]["version"] if with_ffmpeg else None,
        "tessdata": [item["language"] for item in pins["tessdata"]],
        "models": [model["repo"] for model in pins["models"]],
    }, indent=2) + "\n", encoding="utf-8")  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("output", type=Path)
    parser.add_argument("--cache", type=Path, default=ROOT / "tmp" / "engine-cache")
    parser.add_argument("--without-ffmpeg", action="store_true", help="Development builds only.")
    args = parser.parse_args()
    build(args.output.resolve(), args.cache.resolve(), with_ffmpeg=not args.without_ffmpeg)
    print(args.output / "engine")


if __name__ == "__main__":
    main()
