"""The LLM request timeout is configurable and defaults to five minutes for Ollama (R10)."""

import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.config import Settings, load_settings
from pdf2audiobook.errors import ConfigError, LLMError
from pdf2audiobook.llm import OpenAICompatibleProvider
from pdf2audiobook.llm.provider import create_provider
from pdf2audiobook.pipeline import _analysis_stage_fingerprints, _llm_cache_identity

PRIVATE = "PrivateBookSentence"


def _provider(handler, **kwargs) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        provider="ollama",
        base_url="http://127.0.0.1:11434/v1",
        model="local",
        allow_remote=False,
        transport=httpx.MockTransport(handler),
        max_context_tokens=4096,
        max_output_tokens=100,
        **kwargs,
    )


def test_defaults_are_five_minutes_for_ollama_and_unchanged_elsewhere() -> None:
    llm = Settings().llm
    assert llm.ollama.timeout_seconds == 300
    assert llm.openai.timeout_seconds == 60
    assert llm.llama_server.timeout_seconds == 60


def test_config_file_value_reaches_the_selected_provider(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("[llm.ollama]\ntimeout_seconds = 45\n", encoding="utf-8")
    settings, sources = load_settings(config, environ={})
    assert settings.llm.ollama.timeout_seconds == 45
    assert settings.llm.openai.timeout_seconds == 60
    assert sources["llm.ollama.timeout_seconds"].startswith("file:")


def test_environment_override_applies_to_the_selected_provider_only() -> None:
    env = {"PDF2AUDIOBOOK_LLM_TIMEOUT_SECONDS": "120"}
    settings, sources = load_settings(no_config=True, environ=env)
    assert settings.llm.ollama.timeout_seconds == 120
    assert settings.llm.llama_server.timeout_seconds == 60
    assert sources["llm.ollama.timeout_seconds"] == "env:PDF2AUDIOBOOK_LLM_TIMEOUT_SECONDS"
    other, _ = load_settings(
        no_config=True, environ={**env, "PDF2AUDIOBOOK_LLM_PROVIDER": "llama-server"}
    )
    assert other.llm.llama_server.timeout_seconds == 120
    assert other.llm.ollama.timeout_seconds == 300


@pytest.mark.parametrize("value", [0, -5, 3601, "soon"])
def test_out_of_range_values_are_rejected(value: object) -> None:
    with pytest.raises(ConfigError):
        load_settings(
            no_config=True, environ={}, overrides={"llm": {"ollama": {"timeout_seconds": value}}}
        )


def test_the_factory_passes_the_selected_timeout_to_the_http_client() -> None:
    with create_provider(Settings()) as provider:
        assert provider._client.timeout == httpx.Timeout(300, connect=10)
    settings = Settings()
    settings.llm.ollama.timeout_seconds = 5
    with create_provider(settings) as provider:
        assert provider._client.timeout == httpx.Timeout(5, connect=5)


@pytest.mark.ollama_context
def test_context_lookup_uses_a_short_timeout_but_model_load_uses_the_configured_one() -> None:
    seen: dict[str, dict[str, float]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.path] = request.extensions["timeout"]
        if request.url.path == "/api/ps":
            models = [{"name": "local:latest", "model": "local:latest", "context_length": 8192}]
            return httpx.Response(200, json={"models": models})
        if request.url.path == "/api/generate":
            return httpx.Response(200, json={"done": True})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    with _provider(handler, timeout=300.0) as provider:
        provider.complete_json(instructions="x", document_text="y")
    assert seen["/api/generate"]["read"] == 300
    assert seen["/api/ps"]["read"] == 10


def test_a_read_timeout_is_retried_then_reported_with_the_setting_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pdf2audiobook.llm.provider.time.sleep", lambda _seconds: None)
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url.path)
        raise httpx.ReadTimeout("slow", request=request)

    with _provider(handler, max_retries=2, timeout=300.0) as provider:
        with pytest.raises(LLMError) as raised:
            provider.complete_json(instructions="x", document_text=PRIVATE)
    assert len(attempts) == 3
    message = str(raised.value)
    assert "timed out after 300 s" in message and "llm.ollama.timeout_seconds" in message
    assert PRIVATE not in message and "127.0.0.1" not in message


def test_a_connect_timeout_is_still_an_unbilled_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pdf2audiobook.llm.provider.time.sleep", lambda _seconds: None)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("unreachable", request=request)

    with _provider(handler, max_retries=0) as provider:
        with pytest.raises(LLMError) as raised:
            provider.complete_json(instructions="x", document_text="y")
    assert raised.value.unbilled is True
    assert "transport failure" in str(raised.value)


def test_the_timeout_does_not_change_analysis_fingerprints_or_cache_keys() -> None:
    fast, slow = Settings(), Settings()
    slow.llm.ollama.timeout_seconds = 900
    assert _analysis_stage_fingerprints("hash", fast, None) == _analysis_stage_fingerprints(
        "hash", slow, None
    )
    assert _llm_cache_identity(fast) == _llm_cache_identity(slow)


def test_config_show_and_doctor_report_the_effective_value() -> None:
    runner = CliRunner()
    env = {"PDF2AUDIOBOOK_LLM_TIMEOUT_SECONDS": "90"}
    shown = runner.invoke(app, ["config", "show", "--json", "--no-config"], env=env)
    assert shown.exit_code == 0, shown.stderr
    assert json.loads(shown.stdout)["llm"]["ollama"]["timeout_seconds"] == 90
    doctor = runner.invoke(app, ["doctor", "--json", "--no-config"], env=env)
    assert doctor.exit_code == 0, doctor.stderr
    assert json.loads(doctor.stdout)["llm_timeout_seconds"] == 90
