"""Citation and equation processing are two independent, opt-in settings (C1)."""

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.config import Settings, load_settings
from pdf2audiobook.errors import ConfigError

CITATIONS = "PDF2AUDIOBOOK_PROCESS_CITATIONS"
EQUATIONS = "PDF2AUDIOBOOK_PROCESS_EQUATIONS"


def _load(*, toml: str | None = None, env: dict[str, str] | None = None, overrides=None, tmp=None):
    path = None
    if toml is not None:
        path = Path(tmp) / "config.toml"
        path.write_text(toml, encoding="utf-8")
    return load_settings(path, no_config=path is None, environ=env or {}, overrides=overrides)[0]


def test_both_settings_default_to_off() -> None:
    reading = Settings().reading
    assert reading.process_citations is False and reading.process_equations is False


@pytest.mark.parametrize(
    ("key", "other"),
    [("process_citations", "process_equations"), ("process_equations", "process_citations")],
)
def test_the_toml_keys_are_independent(tmp_path: Path, key: str, other: str) -> None:
    settings = _load(toml=f"[reading]\n{key} = true\n", tmp=tmp_path)
    assert getattr(settings.reading, key) is True
    assert getattr(settings.reading, other) is False


@pytest.mark.parametrize(
    ("variable", "key"), [(CITATIONS, "process_citations"), (EQUATIONS, "process_equations")]
)
@pytest.mark.parametrize(("raw", "expected"), [("true", True), ("1", True), ("no", False)])
def test_environment_variables_set_each_setting(
    variable: str, key: str, raw: str, expected: bool
) -> None:
    settings = _load(env={variable: raw})
    assert getattr(settings.reading, key) is expected


def test_cli_overrides_environment_overrides_toml(tmp_path: Path) -> None:
    toml = "[reading]\nprocess_citations = true\n"
    assert _load(toml=toml, tmp=tmp_path).reading.process_citations is True
    assert (
        _load(toml=toml, env={CITATIONS: "false"}, tmp=tmp_path).reading.process_citations is False
    )
    forced = _load(
        toml=toml,
        env={CITATIONS: "false"},
        overrides={"reading": {"process_citations": True}},
        tmp=tmp_path,
    )
    assert forced.reading.process_citations is True


def test_equation_processing_needs_the_llm() -> None:
    with pytest.raises(ConfigError, match="Equation processing needs the LLM") as raised:
        _load(env={EQUATIONS: "true", "PDF2AUDIOBOOK_LLM_ENABLED": "false"})
    assert raised.value.exit_code == 2
    # Citations are deterministic and never need it.
    assert _load(
        env={CITATIONS: "true", "PDF2AUDIOBOOK_LLM_ENABLED": "false"}
    ).reading.process_citations


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[dict[str, bool]]:
    captured: list[dict[str, bool]] = []

    def record(settings: Settings) -> None:
        captured.append(settings.reading.model_dump())

    def fake_analyze(_source, settings, **_kwargs):
        record(settings)
        return tmp_path / "manifest.json"

    def fake_convert(_source, settings, **_kwargs):
        record(settings)
        return []

    monkeypatch.setattr("pdf2audiobook.pipeline.analyze_book", fake_analyze)
    monkeypatch.setattr("pdf2audiobook.pipeline.convert_book", fake_convert)
    return captured


def _invoke(command: str, tmp_path: Path, *flags: str, env: dict[str, str] | None = None):
    source = tmp_path / "book.pdf"
    source.write_bytes(b"%PDF-1.4")
    return CliRunner().invoke(
        app,
        [command, str(source), "--no-config", "--output", str(tmp_path / "out"), *flags],
        env=env,
    )


@pytest.mark.parametrize("command", ["analyze", "convert"])
def test_flags_reach_the_settings_independently(
    command: str, tmp_path: Path, seen: list[dict[str, bool]]
) -> None:
    assert _invoke(command, tmp_path, "--process-citations").exit_code == 0
    assert _invoke(command, tmp_path, "--process-equations").exit_code == 0
    assert _invoke(command, tmp_path).exit_code == 0
    assert seen == [
        {"process_citations": True, "process_equations": False},
        {"process_citations": False, "process_equations": True},
        {"process_citations": False, "process_equations": False},
    ]


@pytest.mark.parametrize("command", ["analyze", "convert"])
def test_negative_flags_override_the_environment(
    command: str, tmp_path: Path, seen: list[dict[str, bool]]
) -> None:
    env = {CITATIONS: "true", EQUATIONS: "true"}
    result = _invoke(command, tmp_path, "--no-process-citations", env=env)
    assert result.exit_code == 0, result.stderr
    assert seen == [{"process_citations": False, "process_equations": True}]


@pytest.mark.parametrize("command", ["analyze", "convert"])
def test_unset_flags_leave_the_environment_in_charge(
    command: str, tmp_path: Path, seen: list[dict[str, bool]]
) -> None:
    assert _invoke(command, tmp_path, env={CITATIONS: "true"}).exit_code == 0
    assert seen == [{"process_citations": True, "process_equations": False}]


@pytest.mark.parametrize("command", ["analyze", "convert"])
def test_equations_with_no_llm_is_a_content_free_usage_error(
    command: str, tmp_path: Path, seen: list[dict[str, bool]]
) -> None:
    result = _invoke(command, tmp_path, "--process-equations", "--no-llm")
    assert result.exit_code == 2
    assert "Equation processing needs the LLM" in result.stderr
    assert str(tmp_path) not in result.stderr
    assert seen == []


def test_config_show_and_doctor_report_both_values() -> None:
    env = {CITATIONS: "true"}
    shown = CliRunner().invoke(app, ["config", "show", "--json", "--no-config"], env=env)
    assert json.loads(shown.stdout)["reading"] == {
        "process_citations": True,
        "process_equations": False,
    }
    doctor: Any = CliRunner().invoke(app, ["doctor", "--json", "--no-config"], env=env)
    payload = json.loads(doctor.stdout)
    assert payload["process_citations"] is True and payload["process_equations"] is False
