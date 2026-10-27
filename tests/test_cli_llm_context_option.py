"""--llm-context-tokens sets the context window the LLM adapter budgets for."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[int]:
    seen: list[int] = []

    def fake_analyze(_source, settings, **_kwargs):
        seen.append(settings.llm.max_context_tokens)
        return tmp_path / "manifest.json"

    monkeypatch.setattr("pdf2audiobook.pipeline.analyze_book", fake_analyze)
    return seen


def _run(tmp_path: Path, *extra: str):
    source = tmp_path / "book.pdf"
    source.write_bytes(b"%PDF-1.4")
    return CliRunner().invoke(
        app, ["analyze", str(source), "--no-config", "--output", str(tmp_path / "out"), *extra]
    )


def test_option_sets_the_context_window(tmp_path: Path, captured: list[int]) -> None:
    result = _run(tmp_path, "--llm-context-tokens", "262144")
    assert result.exit_code == 0, result.stderr
    assert captured == [262144]


def test_default_is_unchanged_without_the_option(tmp_path: Path, captured: list[int]) -> None:
    assert _run(tmp_path).exit_code == 0
    assert captured == [16384]


@pytest.mark.parametrize("value", ["100", "1000"])
def test_too_small_a_window_is_rejected_before_any_work(
    tmp_path: Path, captured: list[int], value: str
) -> None:
    result = _run(tmp_path, "--llm-context-tokens", value)
    assert result.exit_code == 2
    assert captured == []
