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


@pytest.mark.parametrize(
    "bad_llm",
    [
        "SYNTHETIC_PRIVATE_CONFIG_VALUE_173",
        ["SYNTHETIC_PRIVATE_CONFIG_VALUE_173"],
        None,
    ],
)
def test_malformed_cli_llm_section_has_redacted_domain_error(bad_llm) -> None:
    with pytest.raises(ConfigError) as raised:
        load_settings(no_config=True, environ={}, overrides={"llm": bad_llm})
    assert str(raised.value) == "invalid configuration values; check field names and types"
    assert SENTINEL not in str(raised.value)
    assert raised.value.__cause__ is None


def test_nonmapping_cli_override_is_rejected_without_raw_exception() -> None:
    with pytest.raises(ConfigError) as raised:
        load_settings(no_config=True, environ={}, overrides=SENTINEL)
    assert str(raised.value) == "invalid configuration values; check field names and types"
    assert SENTINEL not in str(raised.value)
    assert raised.value.__cause__ is None


def test_toml_scalar_llm_section_is_rejected_before_provider_selection(tmp_path: Path) -> None:
    config = tmp_path / "private.toml"
    config.write_text(f'llm = "{SENTINEL}"\n', encoding="utf-8")
    with pytest.raises(ConfigError) as raised:
        load_settings(config, environ={})
    assert str(raised.value) == "invalid configuration values; check field names and types"
    assert SENTINEL not in str(raised.value)
    assert raised.value.__cause__ is None


@pytest.mark.parametrize("env_override", [False, True], ids=["without-env", "with-env"])
def test_nested_non_table_config_section_is_content_free_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env_override: bool
) -> None:
    config = tmp_path / "settings.toml"
    config.write_text("[tts]\nkitten = 5\n", encoding="utf-8")
    if env_override:
        monkeypatch.setenv("PDF2AUDIOBOOK_TTS_VOICE", "Jasper")

    result = CliRunner().invoke(app, ["config", "show", "--json", "--config", str(config)])

    assert result.exit_code == 2
    assert "PRIVATE" not in result.stderr
    assert "TypeError" not in result.stderr
    assert "invalid configuration values" in result.stderr


@pytest.mark.parametrize("section", ["general", "pdf", "chapters", "llm", "tts", "cache", "audio"])
def test_toml_scalar_sections_keep_diagnostics_content_free(tmp_path: Path, section: str) -> None:
    config = tmp_path / f"{SENTINEL}.toml"
    config.write_text(f'{section} = "{SENTINEL}"\n', encoding="utf-8")
    with pytest.raises(ConfigError) as raised:
        load_settings(config, environ={"PDF2AUDIOBOOK_RESUME": "yes"})
    assert str(raised.value) == "invalid configuration values; check field names and types"
    assert SENTINEL not in str(raised.value)
    assert raised.value.__cause__ is None


@pytest.mark.parametrize(
    "field",
    [
        "max_estimated_cost_usd",
        "input_cost_usd_per_million_tokens",
        "output_cost_usd_per_million_tokens",
    ],
)
@pytest.mark.parametrize("invalid", ["Infinity", "-Infinity", "NaN"])
def test_nonfinite_llm_pricing_never_validates_or_leaks_input(field: str, invalid: str) -> None:
    with pytest.raises(ConfigError) as raised:
        load_settings(no_config=True, environ={}, overrides={"llm": {field: invalid}})
    assert str(raised.value) == "invalid configuration values; check field names and types"
    assert raised.value.__cause__ is None
