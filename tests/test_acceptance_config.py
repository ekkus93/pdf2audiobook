"""Offline acceptance for config precedence, CLI overrides and remote-content consent."""

import json
from pathlib import Path

import httpx
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.config import load_settings
from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm import create_provider

runner = CliRunner()


def test_default_config_and_cli_config_show(monkeypatch):
    monkeypatch.delenv("PDF2AUDIOBOOK_LLM_ENABLED", raising=False)
    monkeypatch.delenv("PDF2AUDIOBOOK_LLM_PROVIDER", raising=False)
    result = runner.invoke(app, ["config", "show", "--no-config", "--sources", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["general"]["resume"] is True
    assert data["llm"]["provider"] == "ollama"
    assert data["_sources"]["llm.provider"] == "built-in"


def test_explicit_false_wins_over_env_and_toml(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text(
        "[general]\nresume = true\n"
        "[llm]\nenabled = true\nallow_remote_content = true\n",
        encoding="utf-8",
    )
    settings, sources = load_settings(
        config,
        environ={
            "PDF2AUDIOBOOK_RESUME": "true",
            "PDF2AUDIOBOOK_LLM_ENABLED": "true",
            "PDF2AUDIOBOOK_ALLOW_REMOTE_CONTENT": "true",
        },
        overrides={
            "general": {"resume": False},
            "llm": {"enabled": False, "allow_remote_content": False},
        },
    )
    assert settings.general.resume is False
    assert settings.llm.enabled is False
    assert settings.llm.allow_remote_content is False
    assert sources["general.resume"] == "CLI"
    assert sources["llm.enabled"] == "CLI"
    assert sources["llm.allow_remote_content"] == "CLI"


def test_environment_explicit_false_overrides_file(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text(
        "[general]\nresume = true\n[llm]\nenabled = true\n"
        "allow_remote_content = true\n",
        encoding="utf-8",
    )
    settings, sources = load_settings(
        config,
        environ={
            "PDF2AUDIOBOOK_RESUME": "false",
            "PDF2AUDIOBOOK_LLM_ENABLED": "false",
            "PDF2AUDIOBOOK_ALLOW_REMOTE_CONTENT": "false",
        },
    )
    assert not settings.general.resume
    assert not settings.llm.enabled
    assert not settings.llm.allow_remote_content
    assert sources["llm.enabled"] == "env:PDF2AUDIOBOOK_LLM_ENABLED"


def test_convert_no_llm_and_no_resume_cli_are_explicit_false(monkeypatch):
    captured = {}

    def fake_convert(source, settings, chapter=None, chapter_range=None, *, force=False):
        captured["settings"] = settings
        captured["source"] = source
        return []

    monkeypatch.setattr("pdf2audiobook.pipeline.convert_book", fake_convert)
    result = runner.invoke(app, [
        "convert", "synthetic.pdf", "--no-config", "--no-llm",
        "--no-resume", "--json",
    ])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"mp3_files": []}
    assert captured["source"] == Path("synthetic.pdf")
    assert captured["settings"].llm.enabled is False
    assert captured["settings"].general.resume is False


def test_analyze_model_override_targets_env_selected_provider(monkeypatch):
    captured = {}

    def fake_analyze(source, settings):
        captured["settings"] = settings
        return Path("synthetic-manifest.json")

    monkeypatch.setenv("PDF2AUDIOBOOK_LLM_PROVIDER", "llama-server")
    monkeypatch.setattr("pdf2audiobook.pipeline.analyze_book", fake_analyze)
    result = runner.invoke(app, [
        "analyze", "synthetic.pdf", "--no-config", "--llm-model", "local-model",
        "--llm-url", "http://127.0.0.1:8080/v1", "--json",
    ])
    assert result.exit_code == 0, result.output
    assert captured["settings"].llm.provider == "llama-server"
    assert captured["settings"].llm.llama_server.model == "local-model"
    assert captured["settings"].llm.llama_server.base_url == "http://127.0.0.1:8080/v1"


def test_remote_content_requires_consent_and_approval_sends_only_requested_text(
    monkeypatch,
):
    from pdf2audiobook.config import Settings

    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    settings = Settings()
    settings.llm.provider = "openai"
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"headings":[]}'}}]}
        )

    transport = httpx.MockTransport(handler)
    try:
        create_provider(settings, transport=transport)
    except LLMError as exc:
        assert "consent" in str(exc).lower() or "allow-remote-content" in str(exc)
    else:
        raise AssertionError("remote provider accepted content without consent")
    assert not requests

    settings.llm.allow_remote_content = True
    with create_provider(settings, transport=transport) as provider:
        result = provider.complete_json(
            instructions="Classify headings", document_text="Synthetic chapter data"
        )
    assert result == {"headings": []}
    assert len(requests) == 1
    payload = json.loads(requests[0].content)
    assert payload["messages"] == [
        {"role": "system", "content": "Classify headings"},
        {"role": "user", "content": "Synthetic chapter data"},
    ]
    assert "tools" not in payload
