"""Live LLM smoke tests require explicit execution and synthetic-only payloads."""

import json

import pytest

from pdf2audiobook.llm import smoke


class FakeProvider:
    last_usage = {"total_tokens": 4}

    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def complete_json(self, *, instructions, document_text):
        self.calls.append((instructions, document_text))
        return {"ok": True}


@pytest.mark.parametrize(
    "arguments",
    [
        ["--provider", "ollama", "--model", "test-model"],
        ["--provider", "openai", "--model", "test-model", "--execute"],
        [
            "--provider",
            "openai",
            "--model",
            "test-model",
            "--execute",
            "--allow-remote-content",
            "--base-url",
            "http://localhost:8080/v1",
        ],
    ],
)
def test_live_smoke_denies_unapproved_network_calls(monkeypatch, arguments):
    def forbidden_provider(_settings):
        pytest.fail("provider constructed before consent was verified")

    monkeypatch.setattr(smoke, "create_provider", forbidden_provider)
    with pytest.raises(SystemExit) as error:
        smoke.run(arguments)
    assert error.value.code == 2


@pytest.mark.parametrize(
    "provider,extra",
    [
        ("ollama", ["--base-url", "http://127.0.0.1:11434/v1"]),
        ("llama-server", ["--base-url", "http://127.0.0.1:8080/v1"]),
        ("openai", ["--allow-remote-content"]),
    ],
)
def test_live_smoke_uses_only_synthetic_text(monkeypatch, capsys, provider, extra):
    fake = FakeProvider()
    captured_settings = []

    def make_provider(settings):
        captured_settings.append(settings)
        return fake

    monkeypatch.setattr(smoke, "create_provider", make_provider)
    assert (
        smoke.run(["--provider", provider, "--model", "synthetic-model", "--execute", *extra]) == 0
    )
    assert len(captured_settings) == 1
    assert captured_settings[0].llm.provider == provider
    assert captured_settings[0].llm.allow_remote_content == (provider == "openai")
    assert len(fake.calls) == 1
    instructions, document_text = fake.calls[0]
    assert "JSON" in instructions
    assert document_text == "Synthetic smoke-test fixture; no user or book content."
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["provider"] == provider
    assert result["model"] == "synthetic-model"
    assert result["reported_tokens"] == {"total_tokens": 4}


def test_live_smoke_fails_closed_on_unexpected_reply(monkeypatch, capsys):
    class BadProvider(FakeProvider):
        def complete_json(self, *, instructions, document_text):
            return {"ok": False}

    monkeypatch.setattr(smoke, "create_provider", lambda _settings: BadProvider())
    assert smoke.run(["--provider", "ollama", "--model", "fixture", "--execute"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert result["error"] == "unexpected_schema"
