"""Offline safety checks for the opt-in live-backend smoke runner."""

import json

import pytest

from pdf2audiobook.llm import smoke


def test_runner_requires_explicit_network_execution():
    with pytest.raises(SystemExit) as error:
        smoke.run(["--provider", "ollama", "--model", "local"])
    assert error.value.code == 2


def test_remote_provider_requires_separate_consent():
    with pytest.raises(SystemExit) as error:
        smoke.run(["--provider", "openai", "--model", "example", "--execute"])
    assert error.value.code == 2


def test_synthetic_fixture_only_and_no_credentials_in_output(monkeypatch, capsys):
    class FakeProvider:
        last_usage = {"total_tokens": 4}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def complete_json(self, *, instructions, document_text):
            assert "Synthetic smoke-test fixture" in document_text
            assert "Return only the JSON object" in instructions
            return {"ok": True}

    monkeypatch.setattr(smoke, "create_provider", lambda settings: FakeProvider())
    assert smoke.run([
        "--provider", "llama-server", "--model", "local",
        "--execute",
    ]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["provider"] == "llama-server"
    assert output["reported_tokens"]["total_tokens"] == 4
