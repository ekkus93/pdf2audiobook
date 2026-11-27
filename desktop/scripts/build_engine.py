"""Build the desktop app's bundled engine (self-contained app spec SC1, SC4).

    uv run --no-project python desktop/scripts/build_engine.py OUTPUT_DIR [--cache DIR]

Produces OUTPUT_DIR/engine: a relocatable CPython (python-build-standalone, as uv installs it), pdf2audiobook and its locked
core dependencies, the Kitten 0.8 ONNX voice path without PyTorch, FFmpeg, English OCR data
and the default voice model. Everything comes from uv.lock or desktop/engine/pins.json and is
checked by hash. Downloads are kept in --cache and reused when their hashes match.

--without-ffmpeg builds without FFmpeg, for local development only; the marker records it.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
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
from email.message import Message
from email.parser import Parser
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
    requirements.write_text(
        "\n".join(entry for name in sorted(wanted) for entry in blocks[name]) + "\n"
    )
    run("uv", "pip", "install", "--python", python, "--break-system-packages",
        "--require-hashes", "--no-deps", "-r", requirements)  # fmt: skip
    run("uv", "build", "--wheel", "--out-dir", work / "wheel", cwd=ROOT, capture_output=True)
    wheel = next((work / "wheel").glob("pdf2audiobook-*.whl"))
    run("uv", "pip", "install", "--python", python, "--break-system-packages", "--no-deps", wheel)


LICENCE_NAMES = ("LICENSE", "LICENCE", "COPYING", "NOTICE", "ThirdPartyNotices")


def _package_licence(meta: Message) -> str:
    expression = meta.get("License-Expression")
    if expression:
        return expression
    text = (meta.get("License") or "").strip()
    if text and "\n" not in text and len(text) <= 80:
        return text
    classifiers = [c.rsplit(" :: ", 1)[-1] for c in meta.get_all("Classifier") or []
                   if c.startswith("License ::")]  # fmt: skip
    return ", ".join(classifiers) or "see the licence text"


def _package_source(meta: Message) -> str:
    urls = dict(
        (label.strip().lower(), url.strip())
        for label, _, url in (item.partition(",") for item in meta.get_all("Project-URL") or [])
    )
    for label in ("source", "source code", "repository", "homepage", "home"):
        if label in urls:
            return urls[label]
    return meta.get("Home-page") or f"https://pypi.org/project/{meta['Name']}/"


def write_notices(engine: Path, pins: dict, cache: Path) -> None:
    """`share/licenses/components.json`: every bundled component with its licence (spec C9).

    The app's About screen lists it and shows each component's licence texts; paths are
    relative to the engine. Texts a component does not ship are added from pinned copies.
    """
    licenses = engine / "share" / "licenses"
    extra = pins["licenses"]
    for name, target in (("apache-2.0", "apache-2.0/LICENSE"), ("espeak-ng", "espeak-ng/COPYING"),
                         ("espeakng-loader", "espeakng-loader/LICENSE")):  # fmt: skip
        (licenses / target).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fetch(extra[name]["url"], extra[name]["sha256"], cache), licenses / target)
    rel = lambda path: str(path.relative_to(engine))  # noqa: E731
    ffmpeg, lame = pins["ffmpeg"], pins["ffmpeg"]["lame"]
    python = pins["python"]
    components = [
        {"name": "Python", "version": python, "license": "PSF-2.0",
         "source": f"https://www.python.org/ftp/python/{python}/Python-{python}.tar.xz "
                   "(built by https://github.com/astral-sh/python-build-standalone, release "
                   f"{pins['python_build']['release']})",
         "files": [rel(next((engine / "lib").glob("python3*/LICENSE.txt")))]},
        {"name": "FFmpeg", "version": ffmpeg["version"], "license": ffmpeg["license"],
         "source": f"{ffmpeg['url']} (sha256 {ffmpeg['sha256']}); "
                   "how it was built is in BUILD.txt",
         "files": [rel(path) for path in sorted((licenses / "ffmpeg").iterdir())]},
        {"name": "LAME", "version": lame["version"], "license": lame["license"],
         "source": f"{lame['url']} (sha256 {lame['sha256']})",
         "files": [rel(path) for path in sorted((licenses / "lame").iterdir())]},
        {"name": "espeak-ng", "version": "1.52.0", "license": "GPL-3.0-or-later",
         "source": "https://github.com/espeak-ng/espeak-ng/tree/"
                   f"{extra['espeak-ng']['commit']} (built by espeakng-loader: "
                   "https://github.com/thewh1teagle/espeakng-loader/tree/"
                   f"{extra['espeakng-loader']['commit']})",
         "files": [rel(licenses / "espeak-ng" / "COPYING")]},
    ]  # fmt: skip
    for item in pins["tessdata"]:
        components.append({
            "name": f"Tesseract OCR data ({item['language']})", "version": "tessdata_fast 4.1.0",
            "license": item["license"], "source": item["url"],
            "files": [rel(licenses / "apache-2.0" / "LICENSE")],
        })  # fmt: skip
    for model in pins["models"]:
        components.append({
            "name": f"{model['repo']} voice model", "version": model["revision"][:12],
            "license": model["license"],
            "source": f"https://huggingface.co/{model['repo']}/tree/{model['revision']}",
            "files": [rel(licenses / "apache-2.0" / "LICENSE")],
        })  # fmt: skip
    site = next((engine / "lib").glob("python3*/site-packages"))
    for info in sorted(site.glob("*.dist-info"), key=lambda path: path.name.lower()):
        meta = Parser().parsestr((info / "METADATA").read_text(encoding="utf-8"), headersonly=True)
        files = sorted(path for path in info.rglob("*") if path.is_file()
                       and (path.parent.name == "licenses" or path.name.startswith(LICENCE_NAMES)))  # fmt: skip
        top = (info / "top_level.txt").read_text(encoding="utf-8").split() if (
            info / "top_level.txt").is_file() else [meta["Name"].replace("-", "_")]  # fmt: skip
        for package in top:
            folder = site / package
            if folder.is_dir():
                files += sorted(p for p in folder.iterdir() if p.is_file()
                                and p.name.startswith(LICENCE_NAMES))  # fmt: skip
        entry = {"name": meta["Name"], "version": meta["Version"],
                 "license": _package_licence(meta), "source": _package_source(meta),
                 "files": [rel(path) for path in files]}  # fmt: skip
        if meta["Name"] == "espeakng_loader" or meta["Name"] == "espeakng-loader":
            entry["license"] = "MIT; includes espeak-ng (GPL-3.0-or-later, listed separately)"
            entry["source"] = (
                "https://github.com/thewh1teagle/espeakng-loader/tree/"
                + extra["espeakng-loader"]["commit"]
            )
            entry["files"] = [rel(licenses / "espeakng-loader" / "LICENSE"),
                              rel(licenses / "espeak-ng" / "COPYING")]  # fmt: skip
        if meta["Name"] == "pdf2audiobook":
            entry["license"] = "Apache-2.0"  # the repository's LICENSE; pyproject names none
            entry["source"] = "https://github.com/ekkus93/pdf2audiobook"
        if not entry["files"] and "Apache" in entry["license"]:
            entry["files"] = [rel(licenses / "apache-2.0" / "LICENSE")]
        if not entry["files"]:
            sys.exit(f"No licence text for the bundled package {meta['Name']}; add one to pins.json")
        components.append(entry)
    (licenses / "components.json").write_text(
        json.dumps({"components": components}, indent=2) + "\n", encoding="utf-8"
    )


def add_addon_lists(engine: Path, cache: Path) -> None:
    """Ship the add-on lists, with wheels built here for the packages that publish only source.

    Users never build anything: each source archive is checked by hash, built once into a wheel
    inside the engine, and its entry then names that wheel and the wheel's own hash.
    """
    data = json.loads(
        (ROOT / "desktop" / "engine" / "addons.lock.json").read_text(encoding="utf-8")
    )
    share = engine / "share" / "pdf2audiobook"
    wheels = share / "wheels"
    wheels.mkdir(parents=True, exist_ok=True)
    python = engine / "bin" / "python3"
    for entries in data["components"].values():
        for entry in entries:
            sdist = entry.pop("sdist", None)
            if sdist is None:
                continue
            algorithm, digest = sdist["hash"].split(":", 1)
            assert algorithm == "sha256", sdist["hash"]
            archive = fetch(sdist["url"], digest, cache)
            named = archive.with_name(sdist["url"].rsplit("/", 1)[-1])
            shutil.copyfile(archive, named)
            with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as temp:
                run(python, "-m", "pip", "wheel", "--quiet", "--no-deps", "--wheel-dir", temp, named,
                    capture_output=True)  # fmt: skip
                built = next(Path(temp).glob("*.whl"))
                shutil.copyfile(built, wheels / built.name)
            named.unlink()
            entry["wheel"] = built.name
            entry["hashes"] = [f"sha256:{sha256(wheels / built.name)}"]
    shutil.copyfile(ROOT / "desktop" / "engine" / "tessdata.json", share / "tessdata.json")
    (share / "addons.lock.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# Only what the engine asks FFmpeg for: MP3 chapters (LAME), the M4B audiobook (AAC in MP4
# with chapters, from a concat list and ffmetadata), decoding WAV, FLAC and MP3 (reference
# recordings, the speech recognizers), raw PCM through pipes, and the atempo filter. Everything
# else, including the network and every external library but LAME, is left out (spec C6).
FFMPEG_CONFIGURE = [
    "--disable-everything", "--disable-autodetect", "--disable-network", "--disable-doc",
    "--disable-debug", "--disable-ffplay", "--disable-ffprobe", "--disable-avdevice",
    "--disable-swscale", "--disable-x86asm", "--enable-static", "--disable-shared",
    # Fully static, C library included, so it runs on any Linux whatever built it.
    "--extra-ldflags=-static",
    "--enable-libmp3lame",
    "--enable-protocol=file,pipe",
    "--enable-demuxer=wav,mp3,flac,aac,mov,concat,ffmetadata,pcm_f32le,pcm_s16le",
    "--enable-muxer=mp3,ipod,mp4,wav,pcm_f32le,pcm_s16le",
    "--enable-decoder=mp3float,mp3,flac,aac,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_f64le,"
    "pcm_u8,pcm_alaw,pcm_mulaw",
    "--enable-encoder=libmp3lame,aac,pcm_s16le,pcm_f32le",
    "--enable-parser=mpegaudio,flac,aac",
    "--enable-filter=abuffer,abuffersink,aformat,anull,aresample,atempo,atrim",
]  # fmt: skip


def build_ffmpeg(pins: dict, cache: Path) -> Path:
    """FFmpeg built from its signed source with LAME linked in, kept in the cache.

    Returns a folder with `ffmpeg` and `licenses/{ffmpeg,lame}`. The build is redone only when
    the pinned sources or the configure options change.
    """
    # configure ignores component names it does not know; smoke_engine.py checks each use.
    recipe = [pins["sha256"], pins["lame"]["sha256"], FFMPEG_CONFIGURE, inspect.getsource(build_ffmpeg)]
    key = hashlib.sha256(json.dumps(recipe).encode()).hexdigest()[:16]
    done = cache / f"ffmpeg-{pins['version']}-{key}"
    if (done / "ffmpeg").is_file():
        return done
    ffmpeg_source = fetch(pins["url"], pins["sha256"], cache)
    lame_source = fetch(pins["lame"]["url"], pins["lame"]["sha256"], cache)
    jobs = str(os.cpu_count() or 2)
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as temp:
        work = Path(temp)
        prefix = work / "prefix"
        with tarfile.open(lame_source) as tar:
            tar.extractall(work, filter="data")
        with tarfile.open(ffmpeg_source) as tar:
            tar.extractall(work, filter="data")
        lame = work / f"lame-{pins['lame']['version']}"
        run("./configure", f"--prefix={prefix}", "--disable-shared", "--enable-static",
            "--disable-frontend", "--disable-decoder", "--disable-gtktest", "--with-pic",
            cwd=lame, capture_output=True)  # fmt: skip
        run("make", f"-j{jobs}", cwd=lame, capture_output=True)
        run("make", "install", cwd=lame, capture_output=True)
        ffmpeg = work / f"ffmpeg-{pins['version']}"
        # The compiler finds LAME through its own search paths, so the configuration FFmpeg
        # records (`ffmpeg -version`) names no folder from the build machine.
        env = {**os.environ, "C_INCLUDE_PATH": str(prefix / "include"),
               "LIBRARY_PATH": str(prefix / "lib")}  # fmt: skip
        run("./configure", *FFMPEG_CONFIGURE, cwd=ffmpeg, env=env, capture_output=True)
        run("make", f"-j{jobs}", "ffmpeg", cwd=ffmpeg, env=env, capture_output=True)
        staging = done.with_suffix(".partial")
        shutil.rmtree(staging, ignore_errors=True)
        (staging / "licenses" / "ffmpeg").mkdir(parents=True)
        (staging / "licenses" / "lame").mkdir(parents=True)
        run("strip", "-o", staging / "ffmpeg", ffmpeg / "ffmpeg")
        # A dynamic loader path in the program headers would tie it to this machine's C library.
        if b"/ld-linux" in (staging / "ffmpeg").read_bytes()[:4096]:
            sys.exit("FFmpeg was not linked statically; install the static C library (libc6-dev)")
        for name in ("COPYING.LGPLv2.1", "LICENSE.md"):
            shutil.copyfile(ffmpeg / name, staging / "licenses" / "ffmpeg" / name)
        for name in ("COPYING", "LICENSE", "README"):
            if (lame / name).is_file():
                shutil.copyfile(lame / name, staging / "licenses" / "lame" / name)
        # The exact build, for the LGPL source offer: where the sources are and how they were built.
        (staging / "licenses" / "ffmpeg" / "BUILD.txt").write_text(
            f"FFmpeg {pins['version']}: {pins['url']}\nsha256 {pins['sha256']}\n\n"
            f"LAME {pins['lame']['version']}: {pins['lame']['url']}\nsha256 {pins['lame']['sha256']}\n\n"
            "LAME configure: --disable-shared --enable-static --disable-frontend --disable-decoder\n"
            f"FFmpeg configure: {' '.join(FFMPEG_CONFIGURE)}\n",
            encoding="utf-8",
        )
        shutil.rmtree(done, ignore_errors=True)
        staging.replace(done)
    return done


def build(output: Path, cache: Path, with_ffmpeg: bool) -> None:
    pins = json.loads(PINS.read_text(encoding="utf-8"))
    engine = output / "engine"
    if engine.exists():
        shutil.rmtree(engine)
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as temp:
        work = Path(temp)
        # The relocatable CPython uv installs, from its pinned archive: older uv versions (CI's
        # pin among them) do not list the newest Python releases.
        build = pins["python_build"]
        with tarfile.open(fetch(build["url"], build["sha256"], cache)) as tar:
            tar.extractall(work, filter="tar")
        shutil.copytree(work / "python", engine, symlinks=True)
        python = engine / "bin" / "python3"
        install_packages(python, work, pins)

    # Console scripts carry the build path in their shebang; the launcher replaces them.
    for script in (engine / "bin").iterdir():
        if script.is_file() and not script.name.startswith("python"):
            first = script.read_bytes()[:256]
            if first.startswith(b"#!") and str(engine).encode() in first:
                script.unlink()
    # Parts of CPython the engine never uses: the Tk GUI toolkit, IDLE and build headers.
    # pip stays: it installs the add-ons (spec SC3); its console scripts go.
    unused = [
        "include", "bin/pip*", "bin/idle*", "bin/2to3*", "bin/pydoc*", "bin/python*-config",
        "lib/tcl*", "lib/tk*", "lib/itcl*", "lib/thread*", "lib/libtcl*", "lib/libtk*",
        # Packages' own test suites, never imported at run time.
        "lib/python3*/site-packages/**/tests",
        "lib/python3*/idlelib", "lib/python3*/tkinter", "lib/python3*/turtledemo",
        "lib/python3*/ensurepip", "lib/python3*/lib2to3", "lib/python3*/lib-dynload/_tkinter*",
    ]  # fmt: skip
    for pattern in unused:
        for path in sorted(engine.glob(pattern)):
            if not path.is_symlink() and not path.exists():
                continue  # inside a folder already removed
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
        built = build_ffmpeg(pins["ffmpeg"], cache)
        shutil.copyfile(built / "ffmpeg", engine / "bin" / "ffmpeg")
        (engine / "bin" / "ffmpeg").chmod(0o755)
        for name in ("ffmpeg", "lame"):
            shutil.copytree(built / "licenses" / name, licenses / name)

    add_addon_lists(engine, cache)
    write_notices(engine, pins, cache)

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
