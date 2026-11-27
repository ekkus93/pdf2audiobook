"""espeak-ng's data folder is reached through a path short enough for its 160-byte buffer.

espeak-ng copies the data path into `path_home[160]` on Linux and silently cuts off a longer
one, then falls back to the folder it was built in, which doesn't exist here: speech fails with
"Error processing file .../phontab". An AppImage that unpacks itself under a long `$TMPDIR` puts
the bundled data well past that. Real espeak runs in the engine smoke test; here a stand-in
`espeakng_loader` checks the path handling.
"""

import os
import sys
import types
from pathlib import Path

import pytest

from pdf2audiobook.tts import espeak_path


def _loader(monkeypatch: pytest.MonkeyPatch, data: Path) -> types.ModuleType:
    module = types.ModuleType("espeakng_loader")
    module.get_data_path = lambda: str(data)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "espeakng_loader", module)
    monkeypatch.delenv("ESPEAK_DATA_PATH", raising=False)
    return module


def _long_data_folder(root: Path) -> Path:
    data = root.joinpath(*["a-rather-long-folder-name"] * 7, "espeak-ng-data")
    data.mkdir(parents=True)
    (data / "phontab").write_bytes(b"phonemes")
    assert len(os.fsencode(data)) > espeak_path.LIMIT
    return data


def test_a_long_data_path_is_replaced_by_a_short_link_to_the_same_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _long_data_folder(tmp_path / "engine")
    monkeypatch.setattr(espeak_path.tempfile, "tempdir", str(tmp_path / "t"))
    (tmp_path / "t").mkdir()
    loader = _loader(monkeypatch, data)
    espeak_path.shorten_espeak_data_path()
    short = loader.get_data_path()
    assert short != str(data)
    # Both forms espeak tries must fit: the folder, and the folder plus "/espeak-ng-data".
    assert len(os.fsencode(short)) + len("/espeak-ng-data") < espeak_path.BUFFER
    assert Path(short).resolve() == data.resolve()
    assert (Path(short) / "phontab").read_bytes() == b"phonemes"
    assert os.environ["ESPEAK_DATA_PATH"] == short
    # Calling it again keeps the same link.
    espeak_path.shorten_espeak_data_path()
    assert loader.get_data_path() == short


def test_a_short_data_path_is_left_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = tmp_path / "espeak-ng-data"
    data.mkdir()
    loader = _loader(monkeypatch, data)
    espeak_path.shorten_espeak_data_path()
    assert loader.get_data_path() == str(data)
    assert "ESPEAK_DATA_PATH" not in os.environ


def test_a_long_temporary_folder_falls_back_to_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _long_data_folder(tmp_path / "engine")
    deep = tmp_path.joinpath(*["another-long-temporary-folder"] * 6)
    deep.mkdir(parents=True)
    monkeypatch.setattr(espeak_path.tempfile, "tempdir", str(deep))
    loader = _loader(monkeypatch, data)
    espeak_path.shorten_espeak_data_path()
    short = loader.get_data_path()
    assert short.startswith("/tmp/")
    assert Path(short).resolve() == data.resolve()


def test_without_espeakng_loader_nothing_happens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "espeakng_loader", None)
    monkeypatch.delenv("ESPEAK_DATA_PATH", raising=False)
    espeak_path.shorten_espeak_data_path()
    assert "ESPEAK_DATA_PATH" not in os.environ
