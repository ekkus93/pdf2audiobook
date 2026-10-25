"""CLI precedence and configuration regressions from the review fixes."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app

runner = CliRunner()


@pytest.mark.parametrize("section", ["general", "pdf", "chapters", "llm", "tts", "cache"])
def test_cli_rejects_scalar_config_sections_with_exit_two(tmp_path: Path, section: str):
    config = tmp_path / "private-config.toml"
    config.write_text(f'{section} = "PRIVATE_SECTION_VALUE"\n')
    result = runner.invoke(app, ["config", "show", "--config", str(config)])
    assert result.exit_code == 2
    assert "invalid configuration values" in result.stderr
    assert "PRIVATE_SECTION_VALUE" not in result.output


@pytest.mark.parametrize("provider_source", ["toml", "env", "cli"])
def test_tts_cli_options_target_effective_provider_and_override_profile(
    tmp_path: Path, monkeypatch, provider_source: str
):
    config = tmp_path / "settings.toml"
    config.write_text(
        '[tts]\nprovider = "piper"\n[tts.piper]\nmodel_path = "profile.onnx"\n'
        'voice = "1"\nspeed = 1.0\n'
    )
    args = [
        "convert",
        str(tmp_path / "book.pdf"),
        "--tts-model",
        "cli.onnx",
        "--voice",
        "3",
        "--speed",
        "1.5",
    ]
    if provider_source == "toml":
        args += ["--config", str(config)]
    elif provider_source == "env":
        monkeypatch.setenv("PDF2AUDIOBOOK_TTS_PROVIDER", "piper")
        args += ["--no-config"]
    else:
        args += ["--no-config", "--tts-provider", "piper"]

    observed = {}

    def fake_convert(_source, settings, **_kwargs):
        observed["settings"] = settings
        return []

    from pdf2audiobook import pipeline

    monkeypatch.setattr(pipeline, "convert_book", fake_convert)
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    settings = observed["settings"]
    assert settings.tts.provider == "piper"
    assert settings.tts.piper.model_path == "cli.onnx"
    assert settings.tts.piper.voice == "3"
    assert settings.tts.piper.speed == 1.5


def test_convert_tts_options_target_kitten_when_selected_by_cli(tmp_path: Path, monkeypatch):
    from pdf2audiobook import pipeline

    observed = []
    monkeypatch.setattr(
        pipeline,
        "convert_book",
        lambda _source, settings, **_kwargs: observed.append(settings) or [],
    )
    result = runner.invoke(
        app,
        [
            "convert",
            str(tmp_path / "book.pdf"),
            "--no-config",
            "--tts-provider",
            "kitten",
            "--tts-model",
            "mini-test",
            "--voice",
            "Jasper-test",
            "--speed",
            "1.25",
            "--sample-rate",
            "22050",
            "--bitrate",
            "96k",
        ],
    )
    assert result.exit_code == 0, result.output
    settings = observed[0]
    assert settings.tts.provider == "kitten"
    assert settings.tts.kitten.model == "mini-test"
    assert settings.tts.kitten.voice == "Jasper-test"
    assert settings.tts.kitten.speed == 1.25
    assert settings.tts.sample_rate == 22050
    assert settings.tts.bitrate == "96k"


def test_negative_cli_switches_revoke_toml_true_values(tmp_path: Path, monkeypatch):
    config = tmp_path / "settings.toml"
    config.write_text(
        "[llm]\nenabled = true\nvision = true\nallow_remote_content = true\n"
        "[chapters]\nallow_single_chapter = true\n"
    )
    from pdf2audiobook import pipeline

    observed = {}

    def fake_analyze(_source, settings):
        observed["settings"] = settings
        return tmp_path / "manifest.json"

    monkeypatch.setattr(pipeline, "analyze_book", fake_analyze)
    result = runner.invoke(
        app,
        [
            "analyze",
            str(tmp_path / "book.pdf"),
            "--config",
            str(config),
            "--no-llm",
            "--no-vision",
            "--no-allow-remote-content",
            "--no-allow-single-chapter",
        ],
    )
    assert result.exit_code == 0, result.output
    settings = observed["settings"]
    assert settings.llm.enabled is False
    assert settings.llm.vision is False
    assert settings.llm.allow_remote_content is False
    assert settings.chapters.allow_single_chapter is False


def test_explicit_unused_cache_directory_warns_and_is_labeled(tmp_path: Path, monkeypatch):
    from pdf2audiobook import logging as app_logging

    monkeypatch.setattr(app_logging, "_CACHE_DIRECTORY_WARNING_EMITTED", False)
    config = tmp_path / "settings.toml"
    config.write_text('[cache]\ndirectory = "/private/cache-path"\n')
    result = runner.invoke(app, ["config", "show", "--config", str(config), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["_unused_settings"] == ["cache.directory"]
    assert "cache_directory_ignored" in result.stderr
    assert "/private/cache-path" not in result.stderr


def test_unset_cache_directory_does_not_warn():
    from pdf2audiobook import logging as app_logging

    app_logging._CACHE_DIRECTORY_WARNING_EMITTED = False
    result = runner.invoke(app, ["config", "show", "--no-config", "--json"])
    assert result.exit_code == 0, result.output
    assert "cache_directory_ignored" not in result.stderr


@pytest.mark.parametrize("source", ["cli", "env", "toml"])
def test_invalid_sample_rate_fails_before_synthesis(tmp_path: Path, monkeypatch, source: str):
    config = tmp_path / "settings.toml"
    config.write_text("[tts]\nsample_rate = 96000\n")
    called = False

    def fake_convert(*_args, **_kwargs):
        nonlocal called
        called = True
        return []

    from pdf2audiobook import pipeline

    monkeypatch.setattr(pipeline, "convert_book", fake_convert)
    args = ["convert", str(tmp_path / "book.pdf")]
    if source == "cli":
        args += ["--no-config", "--sample-rate", "96000"]
    elif source == "env":
        monkeypatch.setenv("PDF2AUDIOBOOK_TTS_SAMPLE_RATE", "96000")
        args += ["--no-config"]
    else:
        args += ["--config", str(config)]
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert called is False
