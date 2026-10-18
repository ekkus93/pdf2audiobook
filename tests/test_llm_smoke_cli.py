"""Offline safety and contract tests for explicitly opted-in live LLM smoke checks."""

from __future__ import annotations

import json

import pytest

from pdf2audiobook.llm import smoke


@pytest.mark.parametrize(
    ("argv", "expected_message"),
    [
        (["--provider", "ollama", "--model", "test"], "--execute"),
        (
            ["--provider", "openai", "--model", "test", "--execute"],
            "--allow-remote-content",
        ),
        (
            [
                "--provider", "openai", "--model", "test", "--execute",
                "--allow-remote-content", "--base-url", "https://example.invalid/v1",
            ],
            "endpoint cannot be overridden",
        ),
    ],
)
def test_smoke_refuses_unconsented_network_or_endpoint_override(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    expected_message: str,
) -> None:
    def unexpected_provider(*args: object, **kwargs: object) -> None:
        pytest.fail("must reject before constructing a network provider")

    monkeypatch.setattr(smoke, "create_provider", unexpected_provider)
    with pytest.raises(SystemExit) as error:
        smoke.run(argv)
    assert error.value.code == 2
    assert expected_message in capsys.readouterr().err


@pytest.mark.parametrize(
    ("provider", "extra"),
    [
        ("ollama", []),
        ("llama-server", []),
        ("openai", ["--allow-remote-content"]),
    ],
)
def test_smoke_sends_only_synthetic_fixture_with_explicit_consent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    provider: str,
    extra: list[str],
) -> None:
    calls: list[tuple[str, str]] = []

    class FakeProvider:
        last_usage = {"total_tokens": 7}

        def __enter__(self) -> FakeProvider:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def complete_json(self, *, instructions: str, document_text: str) -> dict[str, bool]:
            calls.append((instructions, document_text))
            return {"ok": True}

    def fake_create_provider(settings: object) -> FakeProvider:
        assert getattr(getattr(settings, "llm"), "provider") == provider
        return FakeProvider()

    monkeypatch.setattr(smoke, "create_provider", fake_create_provider)
    result = smoke.run(["--provider", provider, "--model", "test-model", "--execute", *extra])
    assert result == 0
    assert len(calls) == 1
    instructions, document_text = calls[0]
    assert '"ok":true' in instructions
    assert document_text == "Synthetic smoke-test fixture; no user or book content."
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "ok": True,
        "provider": provider,
        "model": "test-model",
        "reported_tokens": {"total_tokens": 7},
    }


def test_smoke_unexpected_model_schema_fails_without_leaking_response(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeProvider:
        last_usage: dict[str, int] = {}

        def __enter__(self) -> FakeProvider:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def complete_json(self, *, instructions: str, document_text: str) -> dict[str, object]:
            return {"ok": False, "sensitive": "must-not-be-printed"}

    monkeypatch.setattr(smoke, "create_provider", lambda settings: FakeProvider())
    assert smoke.run(["--provider", "ollama", "--model", "test", "--execute"]) == 1
    output = capsys.readouterr().out
    assert json.loads(output) == {
        "ok": False, "provider": "ollama", "error": "unexpected_schema"
    }
    assert "must-not-be-printed" not in output
