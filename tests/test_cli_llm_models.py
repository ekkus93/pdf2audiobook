"""`llm models` lists what the LLM server serves, for the desktop app's Model field.

Only the server's model list is requested; no book content is involved. Errors stay
content-free: an unreachable server's address is not echoed.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.cli.llm_models import model_overrides
from pdf2audiobook.llm.provider import OpenAICompatibleProvider

runner = CliRunner()


def _json(*args: str) -> tuple[int, dict]:
    result = runner.invoke(app, ["--no-progress", "llm", "models", "--no-config", *args, "--json"])
    lines = [line for line in result.output.splitlines() if line.strip()]
    return result.exit_code, json.loads("\n".join(lines) if lines[0] == "{" else lines[-1])


def test_lists_the_served_models_and_the_configured_one(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = []

    def list_models(self: OpenAICompatibleProvider) -> list[str]:
        asked.append((self.provider, self.base_url))
        return ["qwen3.5:9b", "qwen35-32k:latest"]

    monkeypatch.setattr(OpenAICompatibleProvider, "list_models", list_models)
    code, payload = _json()
    assert code == 0
    assert payload["provider"] == "ollama"
    assert payload["models"] == ["qwen3.5:9b", "qwen35-32k:latest"]
    assert payload["configured"]
    assert asked == [("ollama", "http://127.0.0.1:11434/v1")]


def test_the_provider_and_server_can_be_chosen(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = []
    monkeypatch.setattr(
        OpenAICompatibleProvider,
        "list_models",
        lambda self: asked.append((self.provider, self.base_url)) or ["local.gguf"],
    )
    code, payload = _json("--llm-provider", "llama-server", "--llm-url", "http://127.0.0.1:8081/v1")
    assert code == 0 and payload["provider"] == "llama-server"
    assert asked == [("llama_server", "http://127.0.0.1:8081/v1")]


def test_an_unreachable_server_is_a_content_free_error() -> None:
    address = "http://127.0.0.1:9/v1"
    code, payload = _json("--llm-url", address)
    assert code == 5
    assert payload["ok"] is False
    assert payload["error"]["reason"] == "llm_unreachable"
    assert address not in json.dumps(payload)


def test_openai_still_needs_remote_consent() -> None:
    code, payload = _json("--llm-provider", "openai")
    assert code != 0
    assert "allow-remote-content" in payload["error"]["message"]


def test_an_unknown_provider_is_refused() -> None:
    code, payload = _json("--llm-provider", "elsewhere")
    assert code != 0 and payload["ok"] is False


def test_overrides_turn_the_llm_on_and_place_the_url_under_the_provider() -> None:
    assert model_overrides(None, None) == {"llm": {"enabled": True}}
    assert model_overrides("llama-server", "http://h/v1") == {
        "llm": {
            "enabled": True,
            "provider": "llama-server",
            "llama_server": {"base_url": "http://h/v1"},
        }
    }
