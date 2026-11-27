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

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pdf2audiobook import __version__
from pdf2audiobook.bundle import bundle_root
from pdf2audiobook.errors import AudioError, ConfigError

COMPLETE = ".complete.json"
# Extra pip options, for tests and for a local package mirror; never needed by users.
PIP_OPTIONS_ENV = "PDF2AUDIOBOOK_ADDON_PIP_OPTIONS"


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


def _install_component(name: str, entries: list[dict[str, Any]], pip_options: list[str]) -> None:
    root = addons_root()
    root.mkdir(parents=True, exist_ok=True)
    staging = root / f".{name}.partial"
    final = root / name
    shutil.rmtree(staging, ignore_errors=True)
    share = _share()
    assert share is not None
    with tempfile.TemporaryDirectory() as temp:
        requirements = Path(temp) / "requirements.txt"
        requirements.write_text(_requirements(entries, share / "wheels"), encoding="utf-8")
        command = [
            sys.executable, "-m", "pip", "install", "--no-deps", "--require-hashes",
            "--only-binary", ":all:", "--no-input", "--disable-pip-version-check",
            "--no-warn-script-location", "--quiet", "--target", str(staging),
            "-r", str(requirements), *pip_options,
        ]  # fmt: skip
        try:
            done = subprocess.run(
                command, capture_output=True, text=True, check=False, timeout=3600
            )
        except (OSError, subprocess.TimeoutExpired):
            done = None
    if done is None or done.returncode != 0:
        shutil.rmtree(staging, ignore_errors=True)
        # pip's output names paths and URLs; none of it is shown.
        raise AudioError(
            "The add-on could not be installed. Check the network connection and try again",
            error_reason="addon_install_failed",
        )
    record = {"engine": __version__, "packages": [e["name"] for e in entries]}
    (staging / COMPLETE).write_text(json.dumps(record), encoding="utf-8")
    shutil.rmtree(final, ignore_errors=True)
    os.replace(staging, final)


def _fetch_models(name: str) -> None:
    """Download the add-on's pinned model files with the existing fetchers."""
    if name == "kitten2":
        from pdf2audiobook.tts.catalog import fetch_model

        fetch_model(on_file=None)
    elif name == "audio-check":
        from pdf2audiobook.verification import models as asr

        asr.fetch("whisper", on_file=None)


def install(name: str, *, pip_options: list[str] | None = None) -> dict[str, Any]:
    """Install an add-on's missing components, activate them, then fetch its models."""
    data = _addon(name)
    options = (
        pip_options if pip_options is not None else shlex.split(os.environ.get(PIP_OPTIONS_ENV, ""))
    )
    for component in data["addons"][name]["components"]:
        if not _complete(component):
            _install_component(component, data["components"][component], options)
    activate()
    _fetch_models(name)
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
