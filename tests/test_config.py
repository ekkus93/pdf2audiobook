from pathlib import Path

import pytest

from pdf2audiobook.config import ENV_KEYS, Settings, load_settings, user_config_path
from pdf2audiobook.errors import ConfigError


def test_defaults():
    settings, sources = load_settings(no_config=True, environ={})
    assert settings.llm.provider == "ollama"
    assert sources["llm.provider"] == "built-in"
    assert Settings().pdf.ocr == "auto"
    assert settings.llm.contents is False


def test_contents_analysis_task_has_an_independent_environment_toggle():
    enabled, _ = load_settings(
        no_config=True,
        environ={"PDF2AUDIOBOOK_LLM_CONTENTS": "true"},
    )
    disabled, _ = load_settings(
        no_config=True,
        environ={"PDF2AUDIOBOOK_LLM_CONTENTS": "false"},
    )
    assert enabled.llm.contents is True
    assert enabled.llm.structure is True
    assert disabled.llm.contents is False


def test_pronunciation_dictionary_is_case_insensitive_and_single_token():
    settings = Settings.model_validate({"tts": {"pronunciations": {"Māori": "Mow-ree"}}})
    assert settings.tts.pronunciations == {"māori": "Mow-ree"}
    with pytest.raises(ValueError, match="one word"):
        Settings.model_validate({"tts": {"pronunciations": {"word": "two words"}}})
    with pytest.raises(ValueError, match="unique ignoring case"):
        Settings.model_validate({"tts": {"pronunciations": {"Word": "one", "word": "two"}}})


def test_pronunciation_keys_allow_punctuation_but_reject_markers_and_long_keys():
    settings = Settings.model_validate(
        {"tts": {"pronunciations": {"Dr.": "Doctor", "U.S.,": "United", "(C++)": "seeplus"}}}
    )
    assert settings.tts.pronunciations == {"dr.": "Doctor", "u.s.": "United", "c++": "seeplus"}
    with pytest.raises(ValueError, match="64 characters"):
        Settings.model_validate({"tts": {"pronunciations": {"a" * 65: "word"}}})
    with pytest.raises(ValueError, match="64 characters"):
        Settings.model_validate({"tts": {"pronunciations": {"[[voice:abc]]": "word"}}})


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


@pytest.mark.parametrize("section", ["general", "pdf", "chapters", "llm", "tts", "cache", "audio"])
def test_non_table_config_sections_fail_content_free(tmp_path: Path, section: str):
    config = tmp_path / "bad.toml"
    config.write_text(f"{section} = 7\n")
    with pytest.raises(ConfigError, match="invalid configuration values") as error:
        load_settings(config, environ={"PDF2AUDIOBOOK_RESUME": "false"})
    assert "7" not in str(error.value)


@pytest.mark.parametrize("xdg", [None, "", "relative/config", "/tmp/custom-config"])
def test_user_config_path_ignores_empty_or_relative_xdg(monkeypatch, xdg):
    monkeypatch.setenv("HOME", "/home/example")
    if xdg is None:
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        expected = Path("/home/example/.config/pdf2audiobook/config.toml")
    elif xdg.startswith("/"):
        monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
        expected = Path(xdg) / "pdf2audiobook/config.toml"
    else:
        monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
        expected = Path("/home/example/.config/pdf2audiobook/config.toml")
    assert user_config_path() == expected


def test_environment_values_follow_field_types_and_keep_numeric_strings():
    settings, _ = load_settings(
        no_config=True,
        environ={
            "PDF2AUDIOBOOK_LLM_MODEL": "7",
            "PDF2AUDIOBOOK_OUTPUT_DIR": "2024",
            "PDF2AUDIOBOOK_RESUME": "YES",
            "PDF2AUDIOBOOK_OCR_DPI": "400",
        },
    )
    assert settings.llm.ollama.model == "7"
    assert settings.general.output_dir.endswith("/2024")
    assert settings.general.resume is True
    assert settings.pdf.ocr_dpi == 400


@pytest.mark.parametrize("source", ["cli", "env", "toml"])
def test_relative_output_directory_resolves_from_working_directory(
    tmp_path: Path, monkeypatch, source: str
):
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "settings.toml"
    config.write_text('[general]\noutput_dir = "relative-output"\n')
    kwargs = {}
    if source == "cli":
        kwargs["overrides"] = {"general": {"output_dir": "relative-output"}}
    elif source == "env":
        kwargs["environ"] = {"PDF2AUDIOBOOK_OUTPUT_DIR": "relative-output"}
    else:
        kwargs["config_path"] = config
    settings, _ = load_settings(no_config=source != "toml", **kwargs)
    assert Path(settings.general.output_dir) == tmp_path / "relative-output"


def test_generic_tts_environment_uses_effective_provider_and_specific_wins():
    settings, _ = load_settings(
        no_config=True,
        environ={
            "PDF2AUDIOBOOK_TTS_PROVIDER": "piper",
            "PDF2AUDIOBOOK_TTS_MODEL": "/models/generic.onnx",
            "PDF2AUDIOBOOK_TTS_PIPER_MODEL_PATH": "/models/specific.onnx",
            "PDF2AUDIOBOOK_TTS_VOICE": "3",
            "PDF2AUDIOBOOK_TTS_SPEED": "1.25",
            "PDF2AUDIOBOOK_TTS_PIPER_SPEED": "1.5",
        },
    )
    assert settings.tts.provider == "piper"
    assert settings.tts.piper.model_path == "/models/specific.onnx"
    assert settings.tts.piper.voice == "3"
    assert settings.tts.piper.speed == 1.5


def test_environment_mapping_covers_every_declared_variable():
    environ = {
        "PDF2AUDIOBOOK_OUTPUT_DIR": "2024",
        "PDF2AUDIOBOOK_PROGRESS": "never",
        "PDF2AUDIOBOOK_RESUME": "yes",
        "PDF2AUDIOBOOK_OCR": "never",
        "PDF2AUDIOBOOK_OCR_LANGUAGE": "eng",
        "PDF2AUDIOBOOK_PDF_PASSWORD_ENV": "BOOK_PASSWORD",
        "PDF2AUDIOBOOK_OCR_DPI": "400",
        "PDF2AUDIOBOOK_LLM_ENABLED": "1",
        "PDF2AUDIOBOOK_LLM_VISION": "no",
        "PDF2AUDIOBOOK_LLM_CONTENTS": "yes",
        "PDF2AUDIOBOOK_LLM_PROVIDER": "ollama",
        "PDF2AUDIOBOOK_LLM_MAX_REQUESTS": "10",
        "PDF2AUDIOBOOK_LLM_MAX_OUTPUT_TOKENS": "1000",
        "PDF2AUDIOBOOK_LLM_MAX_REPORTED_TOKENS": "2000",
        "PDF2AUDIOBOOK_LLM_MAX_ESTIMATED_COST_USD": "2.0",
        "PDF2AUDIOBOOK_LLM_INPUT_COST_USD_PER_MILLION_TOKENS": "1.0",
        "PDF2AUDIOBOOK_LLM_OUTPUT_COST_USD_PER_MILLION_TOKENS": "1.0",
        "PDF2AUDIOBOOK_LLM_MODEL": "7",
        "PDF2AUDIOBOOK_LLM_URL": "http://127.0.0.1:11434/v1",
        "PDF2AUDIOBOOK_LLM_TIMEOUT_SECONDS": "420",
        "PDF2AUDIOBOOK_ALLOW_REMOTE_CONTENT": "false",
        "PDF2AUDIOBOOK_LLM_FALLBACK_TO_DETERMINISTIC": "0",
        "PDF2AUDIOBOOK_TTS_PROVIDER": "kitten",
        "PDF2AUDIOBOOK_TTS_MODEL": "7",
        "PDF2AUDIOBOOK_TTS_VOICE": "3",
        "PDF2AUDIOBOOK_TTS_SPEED": "1.25",
        "PDF2AUDIOBOOK_TTS_SAMPLE_RATE": "22050",
        "PDF2AUDIOBOOK_TTS_BITRATE": "96k",
        "PDF2AUDIOBOOK_TTS_MAX_RETRIES": "2",
        "PDF2AUDIOBOOK_TTS_PIPER_MODEL_PATH": "/models/voice.onnx",
        "PDF2AUDIOBOOK_TTS_PIPER_VOICE": "3",
        "PDF2AUDIOBOOK_TTS_PIPER_SPEED": "1.5",
    }
    assert set(environ) == set(ENV_KEYS)
    settings, _ = load_settings(no_config=True, environ=environ)
    assert settings.llm.max_estimated_cost_usd == 2.0
    assert settings.llm.ollama.model == "7"
    assert settings.llm.ollama.timeout_seconds == 420
    assert settings.general.progress == "never"
    assert settings.tts.kitten.model == "7"
    assert settings.tts.kitten.speed == 1.25
    assert settings.tts.piper.speed == 1.5


@pytest.mark.parametrize("value", [96000, 7999, 44101])
def test_tts_rejects_non_mp3_sample_rate(value):
    with pytest.raises(ValueError):
        Settings.model_validate({"tts": {"sample_rate": value}})
