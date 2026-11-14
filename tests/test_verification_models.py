"""ASR model readiness and explicit, checked fetching, offline (audio verification AV2.02)."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.errors import ConfigError
from pdf2audiobook.verification import models
from pdf2audiobook.verification.models import ModelFetchError, ModelSpec, PinnedFile

CONTRACTS = Path(__file__).resolve().parents[1] / "desktop" / "contracts"
runner = CliRunner()


def _pin(name: str, data: bytes) -> PinnedFile:
    return PinnedFile(
        name, f"https://models.example/{name}", len(data), hashlib.sha256(data).hexdigest()
    )


def _zip(member: str = "tiny-model/model.bin") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member, b"weights")
    return buffer.getvalue()


WEIGHTS = b"pretend whisper weights"
ARCHIVE = _zip()


class _Server:
    """Serves pinned bytes by URL and counts requests; nothing reaches the network."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.requests: list[str] = []

    def __call__(self, url: str) -> io.BytesIO:
        self.requests.append(url)
        return io.BytesIO(self.files[url])


@pytest.fixture
def tiny(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    weights, archive = _pin("model.pt", WEIGHTS), _pin("tiny-model.zip", ARCHIVE)
    monkeypatch.setitem(
        models.SPECS,
        "whisper",
        ModelSpec("whisper", "OpenAI Whisper", "medium.en", "r", ("pytest",), (weights,)),
    )
    monkeypatch.setitem(
        models.SPECS,
        "vosk",
        ModelSpec(
            "vosk", "Vosk/Kaldi", "tiny-model", "r", ("pytest",), (archive,), unpack_to="tiny-model"
        ),
    )
    monkeypatch.setenv("PDF2AUDIOBOOK_ASR_DIR", str(tmp_path / "asr"))
    server = _Server({weights.url: WEIGHTS, archive.url: ARCHIVE})
    return {"root": tmp_path / "asr", "server": server, "weights": weights}


def test_the_directory_follows_the_environment(tmp_path: Path) -> None:
    assert models.models_dir({"PDF2AUDIOBOOK_ASR_DIR": str(tmp_path)}) == tmp_path
    assert (
        models.models_dir({"XDG_CACHE_HOME": str(tmp_path)}) == tmp_path / "pdf2audiobook" / "asr"
    )


def test_nothing_is_ready_until_fetched(tiny: dict[str, Any]) -> None:
    readiness = models.readiness("whisper", tiny["root"])
    assert not readiness.ready and readiness.reason == "model_not_downloaded"
    assert readiness.package_version is not None  # pytest stands in for the package


def test_a_missing_package_is_reported_first(
    tiny: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = models.SPECS["whisper"]
    monkeypatch.setitem(
        models.SPECS,
        "whisper",
        ModelSpec(
            spec.name, spec.family, spec.model_id, "r", ("no-such-distribution",), spec.files
        ),
    )
    assert models.readiness("whisper", tiny["root"]).reason == "model_not_installed"


def test_fetch_checks_and_places_the_files(tiny: dict[str, Any]) -> None:
    fetched = models.fetch("whisper", tiny["root"], opener=tiny["server"])
    assert [f.name for f in fetched] == ["model.pt"]
    folder = tiny["root"] / "whisper"
    assert (folder / "model.pt").read_bytes() == WEIGHTS
    assert (folder / "model.pt.sha256").read_text().strip() == tiny["weights"].sha256
    assert models.readiness("whisper", tiny["root"]).ready
    # Already there: nothing is downloaded again.
    assert models.fetch("whisper", tiny["root"], opener=tiny["server"]) == []
    assert len(tiny["server"].requests) == 1


def test_a_wrong_checksum_leaves_nothing_behind(tiny: dict[str, Any]) -> None:
    server = _Server({tiny["weights"].url: b"tampered weights here!!"})
    with pytest.raises(ModelFetchError, match="pinned checksum"):
        models.fetch("whisper", tiny["root"], opener=server)
    assert list((tiny["root"] / "whisper").iterdir()) == []


def test_an_oversized_download_is_stopped(tiny: dict[str, Any]) -> None:
    server = _Server({tiny["weights"].url: WEIGHTS + b"x" * 10})
    with pytest.raises(ModelFetchError, match="larger than expected"):
        models.fetch("whisper", tiny["root"], opener=server)
    assert list((tiny["root"] / "whisper").iterdir()) == []


def test_a_network_failure_is_content_free(tiny: dict[str, Any]) -> None:
    def broken(url: str) -> io.BytesIO:
        raise OSError(f"cannot reach {url} from /home/private/path")

    with pytest.raises(ModelFetchError) as raised:
        models.fetch("whisper", tiny["root"], opener=broken)
    assert "private" not in str(raised.value) and "example" not in str(raised.value)


def test_an_archive_is_unpacked_once_checked(tiny: dict[str, Any]) -> None:
    models.fetch("vosk", tiny["root"], opener=tiny["server"])
    assert (tiny["root"] / "vosk" / "tiny-model" / "model.bin").read_bytes() == b"weights"
    assert models.readiness("vosk", tiny["root"]).ready


def test_an_archive_that_escapes_its_folder_is_refused(
    tiny: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    evil = _zip("../escaped.bin")
    pinned = _pin("tiny-model.zip", evil)
    monkeypatch.setitem(
        models.SPECS,
        "vosk",
        ModelSpec(
            "vosk", "Vosk/Kaldi", "tiny-model", "r", ("pytest",), (pinned,), unpack_to="tiny-model"
        ),
    )
    with pytest.raises(ModelFetchError, match="unsafe"):
        models.fetch("vosk", tiny["root"], opener=_Server({pinned.url: evil}))
    assert not (tiny["root"] / "escaped.bin").exists()


def test_names_resolve_and_unknown_ones_are_refused() -> None:
    assert models.resolve_names([]) == ["whisper", "wav2vec2", "vosk"]
    assert models.resolve_names(["vosk", "whisper", "vosk"]) == ["vosk", "whisper"]
    with pytest.raises(ConfigError):
        models.resolve_names(["deepspeech"])


def test_asr_list_json_follows_the_contract(tiny: dict[str, Any]) -> None:
    result = runner.invoke(app, ["asr", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    contract = json.loads((CONTRACTS / "asr-models.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(payload, contract)
    assert payload["directory"] == str(tiny["root"])
    assert [m["model"] for m in payload["models"]] == ["whisper", "wav2vec2", "vosk"]


def test_listing_never_downloads(tiny: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    def no_network(url: str) -> io.BytesIO:
        raise AssertionError("asr list must not download")

    monkeypatch.setattr(models.urllib.request, "urlopen", no_network)
    assert runner.invoke(app, ["asr", "list"]).exit_code == 0


def test_fetch_asks_first_and_json_needs_yes(
    tiny: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(models.urllib.request, "urlopen", tiny["server"])
    declined = runner.invoke(app, ["asr", "fetch", "whisper"], input="n\n")
    assert declined.exit_code == 1
    assert "1 KB" not in declined.stderr and "models.example" in declined.stderr
    assert tiny["server"].requests == []
    refused = runner.invoke(app, ["asr", "fetch", "whisper", "--json"])
    assert refused.exit_code == 2 and json.loads(refused.stderr)["error"]["type"] == "ConfigError"
    done = runner.invoke(app, ["asr", "fetch", "whisper", "--yes", "--json"])
    assert done.exit_code == 0, done.output
    payload = json.loads(done.stdout)
    assert payload["fetched"] == [{"model": "whisper", "files": ["model.pt"]}]
    assert next(m for m in payload["models"] if m["model"] == "whisper")["ready"] is True
