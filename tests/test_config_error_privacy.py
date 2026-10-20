"""Configuration failures must not echo user-supplied secrets or private paths."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.config import load_settings
from pdf2audiobook.errors import ConfigError


SENTINEL = "SYNTHETIC_PRIVATE_CONFIG_VALUE_173"


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        ("missing", "configuration file not found"),
        ("malformed", "invalid TOML configuration syntax"),
        ("bad_type", "invalid configuration values"),
        ("unknown_key", "invalid configuration values"),
        ("invalid_env", "invalid configuration values"),
        ("invalid_override", "invalid configuration values"),
    ],
)
def test_config_failures_do_not_echo_untrusted_input(
    tmp_path: Path, scenario: str, expected: str
) -> None:
    directory = tmp_path / SENTINEL
    directory.mkdir()
    config = directory / "private.toml"
    environ: dict[str, str] = {}
    overrides = None
    if scenario == "missing":
        pass
    elif scenario == "malformed":
        config.write_text(f'[llm]\nprovider = "ollama"\n[private_{SENTINEL}\n')
    elif scenario == "bad_type":
        config.write_text(f'[general]\nresume = "{SENTINEL}"\n')
    elif scenario == "unknown_key":
        config.write_text(f'[general]\n{SENTINEL} = "value"\n')
    elif scenario == "invalid_env":
        config.write_text("[general]\nresume = true\n")
        environ = {"PDF2AUDIOBOOK_RESUME": SENTINEL}
    else:
        config.write_text("[general]\nresume = true\n")
        overrides = {"general": {"resume": SENTINEL}}

    with pytest.raises(ConfigError) as raised:
        load_settings(config, environ=environ, overrides=overrides)
    assert expected in str(raised.value)
    assert SENTINEL not in str(raised.value)
    assert SENTINEL not in repr(raised.value)
    assert raised.value.__cause__ is None


@pytest.mark.parametrize("json_output", [False, True])
def test_cli_config_failure_redacts_private_path(tmp_path: Path, json_output: bool) -> None:
    private_file = tmp_path / SENTINEL / "missing.toml"
    args = ["config", "show", "--config", str(private_file)]
    if json_output:
        args.append("--json")
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 2
    assert "configuration file not found" in result.output
    assert SENTINEL not in result.output
