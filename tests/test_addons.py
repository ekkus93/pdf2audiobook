"""Desktop add-ons: install, verify, activate and remove (self-contained app spec SC3, TODO 4.2).

Real pip installs small wheels built here, offline (`--no-index --find-links`), into a fake
bundled engine's add-on folder. The model downloads that follow a package install are stubbed.
"""

import base64
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pdf2audiobook import addons, bundle
from pdf2audiobook.cli import app
from pdf2audiobook.errors import AudioError

runner = CliRunner()
pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pip") is None, reason="pip is needed to install add-ons"
)


def _wheel(folder: Path, name: str, version: str) -> tuple[Path, str]:
    """A minimal pure-Python wheel providing module `name` with VALUE = version."""
    module = name.replace("-", "_")
    dist = f"{module}-{version}.dist-info"
    files = {
        f"{module}/__init__.py": f"VALUE = {version!r}\n".encode(),
        f"{dist}/METADATA": f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n".encode(),
        f"{dist}/WHEEL": b"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record = []
    for path, data in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        record.append(f"{path},sha256={digest},{len(data)}")
    record.append(f"{dist}/RECORD,,")
    files[f"{dist}/RECORD"] = ("\n".join(record) + "\n").encode()
    path = folder / f"{module}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for name_in_zip, data in files.items():
            archive.writestr(name_in_zip, data)
    return path, "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    root = tmp_path / "engine"
    share = root / "share" / "pdf2audiobook"
    (share / "wheels").mkdir(parents=True)
    (root / bundle.MARKER).write_text("{}", encoding="utf-8")
    index = tmp_path / "index"
    index.mkdir()
    shared, shared_hash = _wheel(index, "shared-pkg", "1.0")
    alpha, alpha_hash = _wheel(index, "alpha-pkg", "1.0")
    beta, beta_hash = _wheel(share / "wheels", "beta-pkg", "2.0")
    lock = {
        "addons": {
            "kitten2": {"title": "Voice cloning and Kitten 2", "models": "tts fetch kitten2",
                        "components": ["audio-check+kitten2", "kitten2"]},
            "audio-check": {"title": "Audio checking (speech recognizers)", "models": "asr fetch whisper wav2vec2 vosk",
                            "components": ["audio-check", "audio-check+kitten2"]},
        },
        "components": {
            "audio-check+kitten2": [{"name": "shared-pkg", "version": "1.0", "hashes": [shared_hash]}],
            "kitten2": [{"name": "alpha-pkg", "version": "1.0", "hashes": [alpha_hash]}],
            "audio-check": [{"name": "beta-pkg", "version": "2.0", "wheel": beta.name, "hashes": [beta_hash]}],
        },
    }  # fmt: skip
    (share / "addons.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    monkeypatch.setattr(sys, "prefix", str(root))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    # The CLI sets up a bundled engine's environment in os.environ; restore it afterwards.
    for name in ("PATH", "TESSDATA_PREFIX", "PYTHONPATH"):
        monkeypatch.setenv(name, os.environ.get(name, ""))
    monkeypatch.delenv("TESSDATA_PREFIX")
    monkeypatch.setenv("PYTHONPATH", "")
    monkeypatch.setattr(sys, "path", list(sys.path))
    fetched: list[str] = []
    monkeypatch.setattr(addons, "_fetch_models", lambda name: fetched.append(name))
    return {
        "root": root, "index": index, "fetched": fetched, "lock": lock,
        "pip": ["--no-index", "--find-links", str(index)], "data": tmp_path / "data",
    }  # fmt: skip


def _contract(schema: str, payload: object) -> None:
    import jsonschema

    path = Path(__file__).resolve().parents[1] / "desktop" / "contracts" / f"{schema}.schema.json"
    contract = json.loads(path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(contract)
    jsonschema.Draft202012Validator(contract).validate(payload)


def _status(name: str) -> dict:
    return next(item for item in addons.status() if item["name"] == name)


def test_outside_a_bundle_there_are_no_addons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    assert addons.status() == []
    result = runner.invoke(app, ["addons", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert (payload["available"], payload["addons"]) == (False, [])
    _contract("addons-list", payload)


def test_installing_an_addon_installs_its_components_and_fetches_its_models(engine: dict) -> None:
    assert _status("kitten2")["installed"] is False
    addons.install("kitten2", pip_options=engine["pip"])
    status = _status("kitten2")
    assert status["installed"] is True
    assert [c["installed"] for c in status["components"]] == [True, True]
    assert engine["fetched"] == ["kitten2"]
    # The shared component counts for the other add-on too.
    other = _status("audio-check")
    assert other["installed"] is False
    assert [c["installed"] for c in other["components"]] == [False, True]


def test_installed_components_are_activated_for_this_process_and_its_children(engine: dict) -> None:
    addons.install("kitten2", pip_options=engine["pip"])
    environ: dict[str, str] = {"PATH": ""}
    bundle.configure_environment(environ)
    folders = [str(path) for path in addons.active_folders()]
    assert len(folders) == 2 and all(folder in sys.path for folder in folders)
    assert environ["PYTHONPATH"].split(os.pathsep) == folders
    assert importlib.metadata.version("alpha-pkg") == "1.0"


def test_a_hash_mismatch_installs_nothing_and_says_so_without_paths(engine: dict) -> None:
    lock = engine["lock"]
    lock["components"]["kitten2"][0]["hashes"] = ["sha256:" + "0" * 64]
    (engine["root"] / "share" / "pdf2audiobook" / "addons.lock.json").write_text(json.dumps(lock))
    with pytest.raises(AudioError) as raised:
        addons.install("kitten2", pip_options=engine["pip"])
    assert str(engine["data"]) not in str(raised.value) and str(engine["index"]) not in str(
        raised.value
    )
    assert _status("kitten2")["installed"] is False
    # The shared component installed before the failure may stay; the failed one leaves nothing.
    assert sorted(p.name for p in addons.addons_root().iterdir()) == ["audio-check+kitten2"]
    assert engine["fetched"] == []


def test_an_interrupted_install_is_never_used_and_is_cleaned_up(engine: dict) -> None:
    folder = addons.addons_root()
    (folder / ".kitten2.partial").mkdir(parents=True)
    (folder / "kitten2").mkdir()  # No completion record: unusable.
    assert _status("kitten2")["components"][1]["installed"] is False
    assert addons.active_folders() == []
    addons.install("kitten2", pip_options=engine["pip"])
    assert not (folder / ".kitten2.partial").exists()
    assert _status("kitten2")["installed"] is True


def test_removing_keeps_what_another_installed_addon_needs(engine: dict) -> None:
    addons.install("kitten2", pip_options=engine["pip"])
    addons.install("audio-check", pip_options=engine["pip"])
    addons.remove("kitten2")
    assert _status("kitten2")["installed"] is False
    assert _status("audio-check")["installed"] is True
    addons.remove("audio-check")
    assert addons.active_folders() == []
    assert [p.name for p in addons.addons_root().iterdir()] == []


def test_addons_for_another_engine_version_are_not_used(
    engine: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    addons.install("kitten2", pip_options=engine["pip"])
    monkeypatch.setattr(addons, "__version__", "9.9.9")
    status = _status("kitten2")
    assert status["installed"] is False and status["older_version_installed"] is True
    assert addons.active_folders() == []


def test_the_cli_lists_installs_and_removes(engine: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PDF2AUDIOBOOK_ADDON_PIP_OPTIONS", " ".join(engine["pip"]))
    listed = runner.invoke(app, ["addons", "list", "--json"])
    assert listed.exit_code == 0, listed.output
    payload = json.loads(listed.stdout)
    assert payload["available"] is True
    assert [a["name"] for a in payload["addons"]] == ["kitten2", "audio-check"]
    refused = runner.invoke(app, ["addons", "install", "kitten2", "--json"])
    assert refused.exit_code == 2
    installed = runner.invoke(app, ["addons", "install", "kitten2", "--yes", "--json"])
    assert installed.exit_code == 0, installed.output
    assert json.loads(installed.stdout)["addon"]["installed"] is True
    removed = runner.invoke(app, ["addons", "remove", "kitten2", "--json"])
    assert removed.exit_code == 0, removed.output
    assert json.loads(removed.stdout)["addon"]["installed"] is False
    for result in (listed, installed, removed):
        assert str(engine["data"]) not in result.stdout + result.stderr
    _contract("addons-list", payload)
    _contract("addon", json.loads(installed.stdout))
    _contract("addon", json.loads(removed.stdout))
