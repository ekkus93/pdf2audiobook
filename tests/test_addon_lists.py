"""The desktop add-on package lists match uv.lock (self-contained app spec SC3, TODO 4.1)."""

import importlib.util
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMITTED = ROOT / "desktop" / "engine" / "addons.lock.json"


def _generator():
    spec = importlib.util.spec_from_file_location(
        "addon_lists", ROOT / "desktop" / "scripts" / "addon_lists.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_lists_are_what_the_lock_generates() -> None:
    generator = _generator()
    assert COMMITTED.read_text(encoding="utf-8") == generator.render(generator.generate())


def test_the_lists_are_cpu_only_hashed_and_at_locked_versions() -> None:
    data = json.loads(COMMITTED.read_text(encoding="utf-8"))
    locked = {
        (p["name"], p["version"]) for p in tomllib.loads((ROOT / "uv.lock").read_text())["package"]
    }
    entries = [entry for component in data["components"].values() for entry in component]
    names = [entry["name"] for entry in entries]
    assert len(names) == len(set(names)), "a package is in two components"
    assert not [n for n in names if n.startswith(("nvidia-", "cuda-")) or n == "triton"]
    for entry in entries:
        assert entry.get("hashes") or entry.get("sdist", {}).get("hash"), entry["name"]
        if entry["name"] in ("torch", "torchaudio"):
            assert entry["version"].endswith("+cpu") and "/whl/cpu/" in entry["url"]
            assert (entry["name"], entry["version"].removesuffix("+cpu")) in locked
        else:
            assert (entry["name"], entry["version"]) in locked, entry["name"]


def test_pytorch_is_shared_and_each_addon_names_its_components() -> None:
    data = json.loads(COMMITTED.read_text(encoding="utf-8"))
    shared = {entry["name"] for entry in data["components"]["audio-check+kitten2"]}
    assert {"torch"} <= shared
    assert data["addons"]["kitten2"]["components"] == ["audio-check+kitten2", "kitten2"]
    assert data["addons"]["audio-check"]["components"] == ["audio-check", "audio-check+kitten2"]
    whisper = {entry["name"] for entry in data["components"]["audio-check"]}
    assert "openai-whisper" in whisper and "kittenml" not in shared | whisper
