"""`doctor --check-llm` reports whether the configured LLM can take a window (Tauri D4.1)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import LLM_INSTRUCTIONS_ALLOWANCE, app
from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm import OpenAICompatibleProvider

runner = CliRunner()
NEEDED = 4000 + 1024 + 128 + LLM_INSTRUCTIONS_ALLOWANCE  # defaults: chunk, output cap, overhead


def _doctor(*args: str) -> dict[str, Any]:
    result = runner.invoke(app, ["doctor", "--no-config", "--json", *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _served(monkeypatch: pytest.MonkeyPatch, value: int | Exception) -> list[str]:
    seen: list[str] = []

    def served(self: OpenAICompatibleProvider, model: str) -> int:
        seen.append(model)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(OpenAICompatibleProvider, "_ollama_served_context", served)
    return seen


def test_without_the_flag_doctor_does_not_contact_the_llm(monkeypatch) -> None:
    seen = _served(monkeypatch, LLMError("must not be called"))

    assert "llm_check" not in _doctor()
    assert seen == []


def test_ollama_serving_enough_context(monkeypatch) -> None:
    seen = _served(monkeypatch, 262144)

    report = _doctor("--check-llm")["llm_check"]

    assert seen == ["qwen3.5:9b"]
    assert report == {
        "provider": "ollama",
        "checked": True,
        "model": "qwen3.5:9b",
        "configured_context": 16384,
        "output_tokens": 1024,
        "chunk_tokens": 4000,
        "estimated_tokens_needed": NEEDED,
        "reachable": True,
        "served_context": 262144,
        "enough": True,
    }


def test_ollama_serving_a_short_default_context(monkeypatch) -> None:
    _served(monkeypatch, 4096)

    report = _doctor("--check-llm")["llm_check"]

    assert report["reachable"] is True
    assert report["served_context"] == 4096
    assert report["enough"] is False


def test_the_configured_context_also_limits(monkeypatch, tmp_path) -> None:
    _served(monkeypatch, 262144)
    config = tmp_path / "config.toml"
    config.write_text("[llm]\nmax_context_tokens = 8192\n")

    result = runner.invoke(app, ["doctor", "--config", str(config), "--json", "--check-llm"])

    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)["llm_check"]
    # Ollama serves plenty, but the configured 8192 tokens can't hold a window.
    assert report["configured_context"] == 8192
    assert report["estimated_tokens_needed"] > 8192
    assert report["enough"] is False


def test_unreachable_ollama(monkeypatch) -> None:
    _served(monkeypatch, LLMError("Could not read the context length Ollama serves for the model"))

    report = _doctor("--check-llm")["llm_check"]

    assert report["reachable"] is False
    assert report["served_context"] is None
    assert report["enough"] is False


def test_other_providers_and_disabled_llm_are_not_checked(monkeypatch) -> None:
    seen = _served(monkeypatch, 262144)
    monkeypatch.setenv("PDF2AUDIOBOOK_LLM_PROVIDER", "llama-server")
    assert _doctor("--check-llm")["llm_check"] == {"provider": "llama-server", "checked": False}
    monkeypatch.setenv("PDF2AUDIOBOOK_LLM_ENABLED", "false")
    assert _doctor("--check-llm")["llm_check"] == {"provider": "disabled", "checked": False}
    assert seen == []
