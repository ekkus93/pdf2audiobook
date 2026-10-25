from pathlib import Path

import pytest

from pdf2audiobook.config import Settings, load_settings
from pdf2audiobook.errors import ConfigError


def test_defaults():
    settings, sources = load_settings(no_config=True, environ={})
    assert settings.llm.provider == "ollama"
    assert sources["llm.provider"] == "built-in"
    assert Settings().pdf.ocr == "auto"


def test_pronunciation_dictionary_is_case_insensitive_and_single_token():
    settings = Settings.model_validate({"tts": {"pronunciations": {"Māori": "Mow-ree"}}})
    assert settings.tts.pronunciations == {"māori": "Mow-ree"}
    with pytest.raises(ValueError, match="single words"):
        Settings.model_validate({"tts": {"pronunciations": {"word": "two words"}}})
    with pytest.raises(ValueError, match="unique ignoring case"):
        Settings.model_validate({"tts": {"pronunciations": {"Word": "one", "word": "two"}}})


def test_cli_env_file_priority(tmp_path: Path):
    file = tmp_path / "config.toml"
    file.write_text("[llm]\nprovider='openai'\n[general]\nresume=true\n")
    settings, sources = load_settings(
        file,
        environ={"PDF2AUDIOBOOK_LLM_PROVIDER": "llama-server", "PDF2AUDIOBOOK_RESUME": "false"},
        overrides={"llm": {"provider": "ollama"}, "general": {"resume": True}},
    )
    assert settings.llm.provider == "ollama"
    assert settings.general.resume is True
    assert sources["llm.provider"] == "CLI"


def test_env_selected_provider_model():
    settings, sources = load_settings(
        no_config=True,
        environ={
            "PDF2AUDIOBOOK_LLM_PROVIDER": "llama-server",
            "PDF2AUDIOBOOK_LLM_MODEL": "tiny",
        },
    )
    assert settings.llm.llama_server.model == "tiny"
    assert sources["llm.llama_server.model"] == "env:PDF2AUDIOBOOK_LLM_MODEL"


def test_invalid_config(tmp_path: Path):
    file = tmp_path / "bad.toml"
    file.write_text("[pdf]\nunknown = 1\n")
    with pytest.raises(ConfigError):
        load_settings(file, environ={})
    with pytest.raises(ConfigError):
        load_settings(file, no_config=True)
    with pytest.raises(ConfigError):
        load_settings(no_config=True, overrides={"pdf": {"ocr": "magic"}}, environ={})


def test_missing_explicit_config_is_error(tmp_path: Path):
    with pytest.raises(ConfigError, match="not found"):
        load_settings(tmp_path / "missing.toml", environ={})
