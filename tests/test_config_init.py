"""First-run configuration is complete, private, and never replaces user settings."""

import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.config import load_settings
from pdf2audiobook.config_file import default_config_text, initialize_config
from pdf2audiobook.errors import ConfigError


def test_generated_config_preserves_builtin_behavior(tmp_path: Path) -> None:
    path, created = initialize_config(tmp_path / "config.toml")
    assert created
    configured, _ = load_settings(path, environ={})
    defaults, _ = load_settings(no_config=True, environ={})
    assert configured == defaults
    offline, _ = load_settings(path, overrides={"llm": {"enabled": False}}, environ={})
    assert not offline.reading.process_equations
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("existing", [b"# my choices\n[llm]\nenabled=false\n", b"broken\xff"])
def test_initialization_keeps_existing_files_even_if_invalid(
    tmp_path: Path, existing: bytes
) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(existing)
    before = path.stat()
    assert initialize_config(path) == (path, False)
    assert path.read_bytes() == existing
    assert path.stat().st_mtime_ns == before.st_mtime_ns


def test_initialization_keeps_a_dangling_symlink(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.symlink_to(tmp_path / "absent.toml")
    assert initialize_config(path) == (path, False)
    assert path.is_symlink()
    assert not path.exists()


def test_concurrent_initialization_publishes_one_complete_file(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "config.toml"
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: initialize_config(path), range(16)))
    assert sum(created for _, created in results) == 1
    assert path.read_text() == default_config_text()
    assert list(path.parent.iterdir()) == [path]


def test_initialization_failure_is_private_and_leaves_no_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.toml"

    def fail(*args: object) -> None:
        raise PermissionError("PRIVATE_PATH_AND_VALUE")

    monkeypatch.setattr(os, "link", fail)
    with pytest.raises(ConfigError) as error:
        initialize_config(path)
    assert "PRIVATE_PATH_AND_VALUE" not in str(error.value)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("arguments", [["--init"], ["config", "init", "--json"]])
def test_cli_initializes_the_xdg_path_without_persisting_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("PDF2AUDIOBOOK_TTS_VOICE", "PRIVATE_VOICE")
    runner = CliRunner()
    first = runner.invoke(app, arguments)
    assert first.exit_code == 0, first.output
    path = tmp_path / "pdf2audiobook" / "config.toml"
    assert path.read_text() == default_config_text()
    assert "PRIVATE_VOICE" not in path.read_text()
    path.write_text("# edited\n[tts.kitten]\nvoice='Luna'\n")
    second = runner.invoke(app, arguments)
    assert second.exit_code == 0, second.output
    assert "Luna" in path.read_text()
    if "--json" in arguments:
        assert json.loads(first.stdout)["created"] is True
        assert json.loads(second.stdout)["created"] is False


def test_cli_custom_path_and_validation_ignore_environment_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "custom.toml"
    runner = CliRunner()
    result = runner.invoke(app, ["config", "init", "--config", str(path), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["path"] == str(path)
    valid = runner.invoke(app, ["config", "validate", "--config", str(path), "--json"])
    assert valid.exit_code == 0, valid.output
    assert json.loads(valid.stdout)["valid"] is True
    path.write_text("[tts.kitten]\nvoice=123\n")
    monkeypatch.setenv("PDF2AUDIOBOOK_TTS_VOICE", "Jasper")
    invalid = runner.invoke(app, ["config", "validate", "--config", str(path), "--json"])
    assert invalid.exit_code == 2
    assert "invalid configuration values" in json.loads(invalid.stderr)["error"]["message"]
    assert path.read_text() == "[tts.kitten]\nvoice=123\n"
