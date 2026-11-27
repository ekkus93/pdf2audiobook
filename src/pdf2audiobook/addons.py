"""Desktop add-ons: optional features installed on demand next to the bundled engine.

Self-contained app spec SC3. The bundled engine ships `share/pdf2audiobook/addons.lock.json`
(generated from uv.lock) and wheels for packages that publish only source. An add-on is a set of
components; a component is a group of hash-pinned packages installed together with the bundled
pip into its own folder under the user's data directory, for this engine version only:

    $XDG_DATA_HOME/pdf2audiobook/addons/<engine version>/<component>/

A component is staged in a hidden `.<component>.partial` folder and published by renaming it
after pip succeeds and a completion record is written; anything else is ignored and cleaned up.
Packages both add-ons need (PyTorch among them) form one shared component, installed once.
Outside a bundled engine there are no add-ons, and nothing here applies.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pdf2audiobook import __version__
from pdf2audiobook.bundle import bundle_root
from pdf2audiobook.errors import AudioError, ConfigError, InputError
from pdf2audiobook.progress_display import NullReporter, ProgressHandle, ProgressReporter

COMPLETE = ".complete.json"
# A line pip prints as it starts on each requirement (a download, or a wheel shipped here).
_PIP_STARTS = re.compile(r"^(Collecting|Processing) ")
# Extra pip options, for tests and for a local package mirror; never needed by users.
PIP_OPTIONS_ENV = "PDF2AUDIOBOOK_ADDON_PIP_OPTIONS"
# Where OCR language files are downloaded from, as a template with {language}; for tests.
TESSDATA_URL_ENV = "PDF2AUDIOBOOK_TESSDATA_URL"
_LANGUAGE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


def _share() -> Path | None:
    root = bundle_root()
    return None if root is None else root / "share" / "pdf2audiobook"


def lists() -> dict[str, Any] | None:
    """The bundled add-on lists, or None outside a bundled engine."""
    share = _share()
    path = None if share is None else share / "addons.lock.json"
    if path is None or not path.is_file():
        return None
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _data_home() -> Path:
    configured = os.environ.get("XDG_DATA_HOME")
    if configured and Path(configured).expanduser().is_absolute():
        return Path(configured).expanduser()
    return Path.home() / ".local" / "share"


def addons_root(version: str | None = None) -> Path:
    """This engine version's add-on folder (created on first use)."""
    return _data_home() / "pdf2audiobook" / "addons" / (version or __version__)


def _complete(component: str, root: Path | None = None) -> bool:
    record = (root or addons_root()) / component / COMPLETE
    try:
        data = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("engine") == __version__


def _older_versions() -> bool:
    parent = addons_root().parent
    try:
        return any(child.name != __version__ for child in parent.iterdir() if child.is_dir())
    except OSError:
        return False


def status() -> list[dict[str, Any]]:
    """Each add-on with its components' state. Content-free: no paths."""
    data = lists()
    if data is None:
        return []
    older = _older_versions()
    report = []
    for name, addon in data["addons"].items():
        components = [
            {
                "name": component,
                "installed": _complete(component),
                "packages": len(data["components"][component]),
            }
            for component in addon["components"]
        ]
        report.append(
            {
                "name": name,
                "title": addon["title"],
                "installed": all(item["installed"] for item in components),
                "components": components,
                "older_version_installed": older,
            }
        )
    return report


def active_folders() -> list[Path]:
    """Complete components for this engine version, in a stable order."""
    data = lists()
    if data is None:
        return []
    return [addons_root() / name for name in sorted(data["components"]) if _complete(name)]


def activate(environ: Any = os.environ) -> None:
    """Make installed add-ons importable here and in child processes (the voice worker).

    The bundled engine runs in isolated mode, so its own path is extended directly; children
    started without `-I` read `PYTHONPATH`. Add-on folders come after the engine's own packages.
    """
    folders = [str(folder) for folder in active_folders()]
    for folder in folders:
        if folder not in sys.path:
            sys.path.append(folder)
    if folders:
        existing = [part for part in environ.get("PYTHONPATH", "").split(os.pathsep) if part]
        environ["PYTHONPATH"] = os.pathsep.join(
            [*existing, *(f for f in folders if f not in existing)]
        )


def _addon(name: str) -> dict[str, Any]:
    data = lists()
    if data is None:
        raise ConfigError("Add-ons are available only in the desktop app's built-in engine")
    if name not in data["addons"]:
        raise ConfigError("Unknown add-on; choose kitten2 or audio-check")
    return data


def _requirements(entries: Iterable[dict[str, Any]], wheels: Path) -> str:
    lines = []
    for entry in entries:
        hashes = " ".join(f"--hash={value}" for value in entry["hashes"])
        if "wheel" in entry:
            lines.append(f"{wheels / entry['wheel']} {hashes}")
        elif "url" in entry:
            lines.append(f"{entry['name']} @ {entry['url']} {hashes}")
        else:
            lines.append(f"{entry['name']}=={entry['version']} {hashes}")
    return "\n".join(lines) + "\n"


def _pip(command: list[str], on_package: Any) -> int:
    """Run pip, calling `on_package` as it starts each requirement; return its exit status.

    pip's output names paths and URLs, so it is only counted, never shown. If this is
    interrupted (the app's Cancel sends SIGTERM, which the CLI turns into KeyboardInterrupt),
    pip is stopped before the interruption goes on.
    """
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    try:
        assert process.stdout is not None
        for line in process.stdout:
            if _PIP_STARTS.match(line):
                on_package()
        return process.wait()
    except BaseException:
        process.kill()
        process.wait()
        raise


def _install_component(
    name: str, entries: list[dict[str, Any]], pip_options: list[str], packages: ProgressHandle
) -> None:
    root = addons_root()
    root.mkdir(parents=True, exist_ok=True)
    staging = root / f".{name}.partial"
    final = root / name
    shutil.rmtree(staging, ignore_errors=True)
    share = _share()
    assert share is not None
    started = 0

    def on_package() -> None:
        nonlocal started
        # pip names each requirement once; never count past this component's own.
        if started < len(entries):
            started += 1
            packages.advance()

    try:
        with tempfile.TemporaryDirectory() as temp:
            requirements = Path(temp) / "requirements.txt"
            requirements.write_text(_requirements(entries, share / "wheels"), encoding="utf-8")
            command = [
                sys.executable, "-m", "pip", "install", "--no-deps", "--require-hashes",
                "--only-binary", ":all:", "--no-input", "--disable-pip-version-check",
                "--no-warn-script-location", "--progress-bar", "off", "--target", str(staging),
                "-r", str(requirements), *pip_options,
            ]  # fmt: skip
            try:
                status: int | None = _pip(command, on_package)
            except OSError:
                status = None
    except BaseException:
        # Stopped partway: nothing half-installed is left behind.
        shutil.rmtree(staging, ignore_errors=True)
        raise
    if status != 0:
        shutil.rmtree(staging, ignore_errors=True)
        raise AudioError(
            "The add-on could not be installed. Check the network connection and try again",
            error_reason="addon_install_failed",
        )
    # Requirements pip didn't announce (rare) still count once the component is in.
    if started < len(entries):
        packages.advance(len(entries) - started)
    record = {"engine": __version__, "packages": [e["name"] for e in entries]}
    (staging / COMPLETE).write_text(json.dumps(record), encoding="utf-8")
    shutil.rmtree(final, ignore_errors=True)
    os.replace(staging, final)


class _FileSteps:
    """An `on_file` callback counting finished files.

    The fetchers call it as each file starts, so a file counts once the next one starts, and the
    last one when `finish` is called after the fetch returns.
    """

    def __init__(self, handle: ProgressHandle) -> None:
        self.handle = handle
        self.started = 0

    def __call__(self, _: object) -> None:
        if self.started:
            self.handle.advance()
        self.started += 1

    def finish(self) -> None:
        if self.started:
            self.handle.advance()
        self.started = 0


def _fetch_models(name: str, reporter: ProgressReporter) -> None:
    """Download the add-on's pinned model files with the existing fetchers, one step per file."""
    if name == "kitten2":
        from pdf2audiobook.tts import catalog

        missing = catalog.missing_files()
        if not missing:
            return
        files = reporter.stage("Downloading models", len(missing), "files")
        try:
            steps = _FileSteps(files)
            catalog.fetch_model(on_file=steps)
            steps.finish()
        finally:
            files.close()
    elif name == "audio-check":
        from pdf2audiobook.verification import models as asr

        # All three recognizers: a flag is confirmed only when two of them agree.
        plan = asr.fetch_plan(["whisper", "wav2vec2", "vosk"])
        total = sum(len(needed) for _, needed in plan)
        if not total:
            return
        files = reporter.stage("Downloading models", total, "files")
        try:
            steps = _FileSteps(files)
            for model, needed in plan:
                if needed:
                    asr.fetch(model, on_file=steps)
            steps.finish()
        finally:
            files.close()


def install(
    name: str,
    *,
    pip_options: list[str] | None = None,
    reporter: ProgressReporter | None = None,
) -> dict[str, Any]:
    """Install an add-on's missing components, activate them, then fetch its models.

    Progress goes to `reporter`: one step per package, then one per model file. Components
    installed before an interruption stay installed, so installing again continues.
    """
    data = _addon(name)
    progress: ProgressReporter = reporter if reporter is not None else NullReporter()
    options = (
        pip_options if pip_options is not None else shlex.split(os.environ.get(PIP_OPTIONS_ENV, ""))
    )
    missing = [c for c in data["addons"][name]["components"] if not _complete(c)]
    if missing:
        total = sum(len(data["components"][component]) for component in missing)
        packages = progress.stage("Installing packages", total, "packages")
        try:
            for component in missing:
                _install_component(component, data["components"][component], options, packages)
        finally:
            packages.close()
    activate()
    _fetch_models(name, progress)
    return next(item for item in status() if item["name"] == name)


def remove(name: str) -> dict[str, Any]:
    """Remove an add-on's components that no other installed add-on needs."""
    data = _addon(name)
    keep: set[str] = set()
    for other, addon in data["addons"].items():
        if other != name and all(_complete(c) for c in addon["components"]):
            keep.update(addon["components"])
    root = addons_root()
    for component in data["addons"][name]["components"]:
        if component not in keep:
            shutil.rmtree(root / component, ignore_errors=True)
    for leftover in root.glob(".*.partial") if root.is_dir() else ():
        shutil.rmtree(leftover, ignore_errors=True)
    return next(item for item in status() if item["name"] == name)


# OCR languages (spec SC4). PyMuPDF reads every language from one folder, and the bundled one is
# read-only in an AppImage, so added languages go in a writable folder that also holds copies of
# the bundled ones. TESSDATA_PREFIX points there once it exists (see bundle.configure_environment).


def _catalog() -> dict[str, Any] | None:
    share = _share()
    path = None if share is None else share / "tessdata.json"
    if path is None or not path.is_file():
        return None
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _bundled_tessdata() -> Path | None:
    root = bundle_root()
    folder = None if root is None else root / "share" / "tessdata"
    return folder if folder is not None and folder.is_dir() else None


def tessdata_folder() -> Path | None:
    """The writable OCR language folder, once a language has been added."""
    folder = addons_root() / "tessdata"
    return folder if (folder / COMPLETE).is_file() else None


def languages() -> dict[str, list[str]]:
    """OCR languages that can be added, and those ready to use (bundled or added)."""
    catalog = _catalog()
    folder = tessdata_folder() or _bundled_tessdata()
    installed = [] if folder is None else sorted(p.stem for p in folder.glob("*.traineddata"))
    available = [] if catalog is None else sorted(catalog["languages"])
    bundled = _bundled_tessdata()
    shipped = [] if bundled is None else sorted(p.stem for p in bundled.glob("*.traineddata"))
    return {"available": available, "installed": installed, "bundled": shipped}


def _git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def _language_folder() -> Path:
    folder = addons_root() / "tessdata"
    if not (folder / COMPLETE).is_file():
        folder.mkdir(parents=True, exist_ok=True)
        bundled = _bundled_tessdata()
        for source in [] if bundled is None else bundled.glob("*.traineddata"):
            shutil.copyfile(source, folder / source.name)
        (folder / COMPLETE).write_text(json.dumps({"engine": __version__}), encoding="utf-8")
    return folder


def add_languages(codes: list[str]) -> dict[str, list[str]]:
    """Download OCR languages, each checked against the pinned size and git blob hash."""
    catalog = _catalog()
    if catalog is None:
        raise ConfigError(
            "Adding OCR languages is available only in the desktop app's built-in engine"
        )
    for code in codes:
        if not _LANGUAGE.match(code) or code not in catalog["languages"]:
            raise ConfigError("Unknown OCR language; see 'addons languages --json'")
    folder = _language_folder()
    template = os.environ.get(TESSDATA_URL_ENV) or catalog["url"]
    for code in codes:
        target = folder / f"{code}.traineddata"
        if target.is_file():
            continue
        pinned = catalog["languages"][code]
        partial = folder / f".{code}.partial"
        try:
            with urllib.request.urlopen(template.format(language=code), timeout=120) as response:
                data = response.read(pinned["size"] + 1)
        except OSError:
            raise InputError(
                "The OCR language could not be downloaded. Check the network connection and try again"
            ) from None
        if len(data) != pinned["size"] or _git_blob(data) != pinned["git_blob"]:
            raise InputError("The downloaded OCR language did not match its pinned checksum")
        partial.write_bytes(data)
        os.replace(partial, target)
    return languages()


def remove_language(code: str) -> dict[str, list[str]]:
    """Remove an added OCR language; the bundled ones stay."""
    bundled = _bundled_tessdata()
    if not _LANGUAGE.match(code) or (
        bundled is not None and (bundled / f"{code}.traineddata").is_file()
    ):
        raise ConfigError("Only added OCR languages can be removed")
    folder = tessdata_folder()
    if folder is not None:
        (folder / f"{code}.traineddata").unlink(missing_ok=True)
    return languages()
