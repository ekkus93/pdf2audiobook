"""The effective config view must not print credentials from URLs or fields."""

import json

import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.config import _redact_public_value


@pytest.mark.parametrize("sources", [False, True])
@pytest.mark.parametrize("configured_by", ["toml", "env"])
def test_config_show_redacts_url_userinfo_query_and_secret_fields(
    tmp_path, monkeypatch, sources, configured_by
):
    secret_parts = ("PRIVATE_USER", "sk-URL_PASSWORD", "sk-QUERY_VALUE", "sk-FRAGMENT")
    config = tmp_path / "settings.toml"
    config.write_text(
        '[llm]\nprovider = "ollama"\n'
        "[llm.ollama]\n"
        'base_url = "http://PRIVATE_USER:sk-URL_PASSWORD@localhost:11434/v1?key=sk-QUERY_VALUE#sk-FRAGMENT"\n'
        'api_key_env = "MY_PRIVATE_API_KEY_ENV"\n',
        encoding="utf-8",
    )
    args = ["config", "show", "--json"]
    if configured_by == "toml":
        args.extend(["--config", str(config)])
    else:
        args.append("--no-config")
        monkeypatch.setenv("PDF2AUDIOBOOK_LLM_PROVIDER", "ollama")
        monkeypatch.setenv(
            "PDF2AUDIOBOOK_LLM_URL",
            "http://PRIVATE_USER:sk-URL_PASSWORD@localhost:11434/v1?key=sk-QUERY_VALUE#sk-FRAGMENT",
        )
    if sources:
        args.append("--sources")

    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    output = result.stdout
    for secret in secret_parts:
        assert secret not in output
    assert "MY_PRIVATE_API_KEY_ENV" in output or configured_by == "env"
    assert "***" in output
    assert "?key=sk-QUERY_VALUE" not in output
    if configured_by == "toml":
        assert payload["llm"]["ollama"]["api_key_env"] == "MY_PRIVATE_API_KEY_ENV"


def test_config_redaction_does_not_infer_secrets_from_user_dictionary_keys():
    assert _redact_public_value(
        {
            "api_key": "sk-PRIVATE_KEY",
            "access_token": "PRIVATE_TOKEN",
            "password_env": "BOOK_PASSWORD_ENV",
        }
    ) == {
        "api_key": "sk-PRIVATE_KEY",
        "access_token": "PRIVATE_TOKEN",
        "password_env": "BOOK_PASSWORD_ENV",
    }


def test_config_redaction_hides_unparseable_url_values():
    assert _redact_public_value("http:///PRIVATE_URL_VALUE") == "***"


@pytest.mark.parametrize(
    ("password", "secret"),
    [
        ("private#HASH_SECRET", "HASH_SECRET"),
        ("private?QUERY_SECRET", "QUERY_SECRET"),
        ("private/PATH_SECRET", "PATH_SECRET"),
        ("private@AT_SECRET", "AT_SECRET"),
    ],
)
@pytest.mark.parametrize("sources", [False, True], ids=["config-only", "with-sources"])
def test_config_show_redacts_reserved_characters_in_url_password(
    tmp_path, password, secret, sources
):
    config = tmp_path / "settings.toml"
    config.write_text(
        '[llm]\nprovider = "ollama"\n[llm.ollama]\n'
        f'base_url = "http://PRIVATE_USER:{password}@localhost:11434/v1"\n',
        encoding="utf-8",
    )
    arguments = ["config", "show", "--json", "--config", str(config)]
    if sources:
        arguments.append("--sources")

    result = CliRunner().invoke(app, arguments)

    assert result.exit_code == 0, result.stderr
    assert secret not in result.stdout
    assert "PRIVATE_USER" not in result.stdout
    assert json.loads(result.stdout)["llm"]["ollama"]["base_url"].startswith("http://***@localhost")


@pytest.mark.parametrize("sources", [False, True], ids=["config-only", "with-sources"])
def test_declared_secret_config_field_is_redacted(tmp_path, monkeypatch, sources):
    import pdf2audiobook.config as app_config

    monkeypatch.setattr(app_config, "_SECRET_CONFIG_PATHS", frozenset({"llm.ollama.model"}))
    config = tmp_path / "settings.toml"
    config.write_text(
        '[llm]\nprovider = "ollama"\n[llm.ollama]\nmodel = "PRIVATE_MODEL_SECRET_123"\n',
        encoding="utf-8",
    )
    arguments = ["config", "show", "--json", "--config", str(config)]
    if sources:
        arguments.append("--sources")

    result = CliRunner().invoke(app, arguments)

    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["llm"]["ollama"]["model"] == "***"
    assert "PRIVATE_MODEL_SECRET_123" not in result.stdout


def test_config_show_keeps_numeric_limits_rates_and_pronunciation_keys_visible(tmp_path):
    config = tmp_path / "settings.toml"
    config.write_text(
        "[llm]\nmax_reported_tokens = 123\n"
        "input_cost_usd_per_million_tokens = 2.5\n"
        "output_cost_usd_per_million_tokens = 7.5\n"
        '[tts.pronunciations]\n"Dr." = "Doctor"\n',
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["config", "show", "--json", "--config", str(config)])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["llm"]["max_reported_tokens"] == 123
    assert payload["llm"]["input_cost_usd_per_million_tokens"] == 2.5
    assert payload["llm"]["output_cost_usd_per_million_tokens"] == 7.5
    assert payload["tts"]["pronunciations"] == {"dr.": "Doctor"}
