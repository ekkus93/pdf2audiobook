"""Generate the add-on package lists from uv.lock (self-contained app spec SC3, TODO 4.1).

    uv run python desktop/scripts/addon_lists.py            # rewrite desktop/engine/addons.lock.json
    uv run python desktop/scripts/addon_lists.py --check    # fail if it is out of date

Each add-on is what its feature needs beyond the bundled engine, resolved from uv.lock for the
engine's platform (CPython 3.11, Linux x86-64). Packages are grouped into components by the set
of add-ons that need them, so a package both need (PyTorch among them) is installed once.
PyTorch and torchaudio are replaced by their CPU builds (spec C5), and the CUDA, NVIDIA and
Triton packages, which only a GPU uses, are left out. Every entry carries its hashes.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

from packaging.markers import Marker

ROOT = Path(__file__).resolve().parents[2]
PINS = ROOT / "desktop" / "engine" / "pins.json"
OUTPUT = ROOT / "desktop" / "engine" / "addons.lock.json"

# The bundled engine's platform, as environment markers see it.
ENGINE = {
    "implementation_name": "cpython",
    "implementation_version": "3.11.18",
    "os_name": "posix",
    "platform_machine": "x86_64",
    "platform_python_implementation": "CPython",
    "platform_system": "Linux",
    "python_full_version": "3.11.18",
    "python_version": "3.11",
    "sys_platform": "linux",
    "extra": "",
}

ADDONS = {
    "kitten2": {
        "title": "Voice cloning and Kitten 2",
        "roots": ["kittenml"],
        "models": "tts fetch kitten2",
    },
    "audio-check": {
        "title": "Audio checking (Whisper)",
        "roots": ["openai-whisper"],
        "models": "asr fetch whisper",
    },
}


def _gpu_only(name: str) -> bool:
    return name.startswith(("nvidia-", "cuda-")) or name == "triton"


class Lock:
    def __init__(self, data: dict) -> None:
        self.packages: dict[tuple[str, str], dict] = {
            (package["name"], package["version"]): package for package in data["package"]
        }
        self.by_name: dict[str, list[dict]] = {}
        for package in data["package"]:
            self.by_name.setdefault(package["name"], []).append(package)

    def find(self, edge: dict) -> dict:
        if "version" in edge:
            return self.packages[(edge["name"], edge["version"])]
        (package,) = self.by_name[edge["name"]]
        return package

    def closure(self, roots: list[dict], *, include_roots: bool = True) -> dict[str, dict]:
        """Packages reachable from `roots` on the engine's platform, by name."""
        found: dict[str, dict] = {}
        pending = [(edge, include_roots) for edge in roots]
        while pending:
            edge, keep = pending.pop()
            if "marker" in edge and not Marker(edge["marker"]).evaluate(ENGINE):
                continue
            package = self.find(edge)
            extras = edge.get("extra", [])
            seen = found.get(package["name"])
            if seen is not None and not extras:
                continue
            if keep:
                found[package["name"]] = package
            pending.extend((dep, True) for dep in package.get("dependencies", []))
            for extra in extras:
                optional = package.get("optional-dependencies", {}).get(extra, [])
                pending.extend((dep, True) for dep in optional)
        return found


def _requirement(package: dict) -> dict:
    hashes = [wheel["hash"] for wheel in package.get("wheels", [])]
    entry: dict = {"name": package["name"], "version": package["version"]}
    if hashes:
        entry["hashes"] = sorted(hashes)
    else:
        # Source only: the engine build turns it into a wheel from this hashed archive.
        entry["sdist"] = {"url": package["sdist"]["url"], "hash": package["sdist"]["hash"]}
    return entry


def generate() -> dict:
    lock = Lock(tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8")))
    pins = json.loads(PINS.read_text(encoding="utf-8"))
    project = lock.by_name["pdf2audiobook"][0]
    onnx = [{"name": name} for name in pins["packages"]["kittenml_onnx"] if name != "kittenml"]
    base = set(lock.closure(project["dependencies"])) | set(lock.closure(onnx)) | {"kittenml"}

    needs: dict[str, set[str]] = {}
    packages: dict[str, dict] = {}
    for addon, spec in ADDONS.items():
        roots = [{"name": root} for root in spec["roots"]]
        # kittenml is in the base engine without its dependencies; the add-on supplies them.
        reach = lock.closure(roots, include_roots=spec["roots"] != ["kittenml"])
        for name, package in reach.items():
            if name in base or _gpu_only(name):
                continue
            needs.setdefault(name, set()).add(addon)
            packages[name] = package

    cpu = pins["addons"]["cpu_wheels"]
    components: dict[str, list[dict]] = {}
    for name in sorted(packages):
        key = "+".join(sorted(needs[name]))
        if name in cpu:
            locked = packages[name]["version"]
            if cpu[name]["version"] != f"{locked}+cpu":
                sys.exit(f"{name}: the CPU pin is not the locked version {locked}")
            entry = {"name": name, "version": cpu[name]["version"], "url": cpu[name]["url"],
                     "hashes": [cpu[name]["sha256"]]}  # fmt: skip
        else:
            entry = _requirement(packages[name])
        components.setdefault(key, []).append(entry)

    return {
        "comment": "Generated by desktop/scripts/addon_lists.py from uv.lock; do not edit.",
        "platform": {
            "python": ENGINE["python_full_version"],
            "machine": "x86_64",
            "system": "Linux",
        },
        "addons": {
            name: {
                "title": spec["title"],
                "models": spec["models"],
                "components": sorted(key for key in components if name in key.split("+")),
            }
            for name, spec in ADDONS.items()
        },
        "components": components,
    }


def render(data: dict) -> str:
    return json.dumps(data, indent=2, sort_keys=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--check", action="store_true", help="Fail if the committed lists are out of date."
    )
    args = parser.parse_args()
    text = render(generate())
    if args.check:
        if OUTPUT.read_text(encoding="utf-8") != text:
            sys.exit(
                f"{OUTPUT.relative_to(ROOT)} is out of date; run desktop/scripts/addon_lists.py"
            )
        return
    OUTPUT.write_text(text, encoding="utf-8")
    print(OUTPUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
