"""Adding OCR languages to the desktop app's engine (self-contained app spec SC4, TODO 4.3)."""

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pdf2audiobook import addons, bundle
from pdf2audiobook.cli import app
from pdf2audiobook.errors import ConfigError, InputError

runner = CliRunner()


def _contract(schema: str, payload: object) -> None:
    import jsonschema

    path = Path(__file__).resolve().parents[1] / "desktop" / "contracts" / f"{schema}.schema.json"
    contract = json.loads(path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(contract)
    jsonschema.Draft202012Validator(contract).validate(payload)


def _blob(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


@pytest.fixture
def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    root = tmp_path / "engine"
    share = root / "share"
    (share / "tessdata").mkdir(parents=True)
    (share / "tessdata" / "eng.traineddata").write_bytes(b"bundled english")
    (root / bundle.MARKER).write_text("{}", encoding="utf-8")
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    files = {"deu": b"german data", "fra": b"french data", "eng": b"bundled english"}
    for code, data in files.items():
        (upstream / f"{code}.traineddata").write_bytes(data)
    catalog = {
        "url": "https://example.invalid/{language}.traineddata",
        "languages": {
            code: {"size": len(data), "git_blob": _blob(data)} for code, data in files.items()
        },
    }
    (share / "pdf2audiobook").mkdir()
    (share / "pdf2audiobook" / "tessdata.json").write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setattr(sys, "prefix", str(root))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    # The CLI sets up a bundled engine's environment in os.environ; restore it afterwards.
    for name in ("PATH", "TESSDATA_PREFIX", "PYTHONPATH"):
        monkeypatch.setenv(name, os.environ.get(name, ""))
    monkeypatch.delenv("TESSDATA_PREFIX")
    monkeypatch.setenv(addons.TESSDATA_URL_ENV, upstream.as_uri() + "/{language}.traineddata")
    return {"root": root, "upstream": upstream, "data": tmp_path / "data", "catalog": catalog}


def test_the_bundled_language_is_listed_and_others_can_be_added(engine: dict) -> None:
    report = addons.languages()
    assert report["installed"] == ["eng"]
    assert report["available"] == ["deu", "eng", "fra"]
    assert report["bundled"] == ["eng"]


def test_an_added_language_is_used_together_with_the_bundled_one(engine: dict) -> None:
    addons.add_languages(["deu"])
    assert addons.languages()["installed"] == ["deu", "eng"]
    environ: dict[str, str] = {"PATH": ""}
    bundle.configure_environment(environ)
    folder = Path(environ["TESSDATA_PREFIX"])
    assert sorted(p.name for p in folder.glob("*.traineddata")) == [
        "deu.traineddata",
        "eng.traineddata",
    ]
    assert (folder / "eng.traineddata").read_bytes() == b"bundled english"


def test_a_corrupted_download_is_refused_and_leaves_nothing(engine: dict) -> None:
    (engine["upstream"] / "fra.traineddata").write_bytes(b"french dat4")
    with pytest.raises(InputError) as raised:
        addons.add_languages(["fra"])
    assert str(engine["upstream"]) not in str(raised.value)
    assert addons.languages()["installed"] == ["eng"]
    folder = addons.addons_root() / "tessdata"
    assert not [p for p in folder.iterdir() if p.name.startswith("fra") or p.suffix == ".partial"]


def test_unknown_or_unsafe_codes_are_refused(engine: dict) -> None:
    for code in ("xyz", "../eng", ""):
        with pytest.raises(ConfigError):
            addons.add_languages([code])


def test_removing_keeps_the_bundled_language(engine: dict) -> None:
    addons.add_languages(["deu", "fra"])
    addons.remove_language("fra")
    assert addons.languages()["installed"] == ["deu", "eng"]
    with pytest.raises(ConfigError):
        addons.remove_language("eng")


def test_the_cli_lists_adds_and_removes_languages(engine: dict) -> None:
    listed = runner.invoke(app, ["addons", "languages", "--json"])
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.stdout)["installed"] == ["eng"]
    refused = runner.invoke(app, ["addons", "add-language", "deu", "--json"])
    assert refused.exit_code == 2
    added = runner.invoke(app, ["addons", "add-language", "deu", "--yes", "--json"])
    assert added.exit_code == 0, added.output
    assert json.loads(added.stdout)["installed"] == ["deu", "eng"]
    removed = runner.invoke(app, ["addons", "remove-language", "deu", "--json"])
    assert json.loads(removed.stdout)["installed"] == ["eng"]
    for result in (listed, added, removed):
        assert str(engine["data"]) not in result.stdout + result.stderr
        _contract("addon-languages", json.loads(result.stdout))
