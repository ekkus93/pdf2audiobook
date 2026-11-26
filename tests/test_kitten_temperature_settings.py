"""The Kitten 2 sampling temperature setting (Kitten 2 temperature spec K1, K4)."""

import json
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.config import Settings, load_settings
from pdf2audiobook.errors import ConfigError
from pdf2audiobook.tts.selection import settings_for_book_tts

ENV = "PDF2AUDIOBOOK_TTS_KITTEN_TEMPERATURE"
runner = CliRunner()


def _load(*, toml: str | None = None, env: dict[str, str] | None = None, overrides=None, tmp=None):
    path = None
    if toml is not None:
        path = Path(tmp) / "config.toml"
        path.write_text(toml, encoding="utf-8")
    return load_settings(path, no_config=path is None, environ=env or {}, overrides=overrides)


def test_the_default_is_low() -> None:
    assert Settings().tts.kitten.temperature == 0.2


def test_flag_over_environment_over_config_over_default(tmp_path: Path) -> None:
    toml = "[tts.kitten]\ntemperature = 0.5\n"
    assert _load(toml=toml, tmp=tmp_path)[0].tts.kitten.temperature == 0.5
    from_env, origins = _load(toml=toml, env={ENV: "0.4"}, tmp=tmp_path)
    assert from_env.tts.kitten.temperature == 0.4
    assert origins["tts.kitten.temperature"] == f"env:{ENV}"
    flagged = _load(
        toml=toml,
        env={ENV: "0.4"},
        overrides={"tts": {"kitten": {"temperature": 0.2}}},
        tmp=tmp_path,
    )[0]
    assert flagged.tts.kitten.temperature == 0.2


@pytest.mark.parametrize("value", ["0.04", "1.51", "nan", "inf", "-0.3"])
def test_out_of_range_values_are_refused_without_content(tmp_path: Path, value: str) -> None:
    secret = tmp_path / "private-book-folder"
    secret.mkdir()
    with pytest.raises(ConfigError) as raised:
        _load(toml=f"[tts.kitten]\ntemperature = {value}\n", tmp=secret)
    assert str(secret) not in str(raised.value)


@pytest.mark.parametrize("value", ["0.05", "1.5"])
def test_the_range_bounds_are_accepted(value: str) -> None:
    assert _load(env={ENV: value})[0].tts.kitten.temperature == float(value)


def test_a_profile_sets_the_temperature_unless_the_flag_does(tmp_path: Path) -> None:
    settings = _load(toml='[tts.profiles."Novel"]\ntemperature = 0.25\n', tmp=tmp_path)[0]
    assert settings_for_book_tts(settings, "Novel").tts.kitten.temperature == 0.25
    explicit = settings_for_book_tts(settings, "Novel", explicit=frozenset({"temperature"}))
    assert explicit.tts.kitten.temperature == 0.2


def _capture(monkeypatch: pytest.MonkeyPatch, target: str) -> list[Settings]:
    seen: list[Settings] = []

    def record(*args, **_kwargs):
        seen.extend(arg for arg in args if isinstance(arg, Settings))
        return []

    monkeypatch.setattr(target, record)
    return seen


def test_convert_takes_the_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _capture(monkeypatch, "pdf2audiobook.pipeline.convert_book")
    source = tmp_path / "book.pdf"
    source.write_bytes(b"synthetic input")
    result = runner.invoke(
        app, ["convert", str(source), "--no-config", "--tts-temperature", "0.2", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert seen[0].tts.kitten.temperature == 0.2


def test_batch_takes_the_flag_over_a_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _capture(monkeypatch, "pdf2audiobook.pipeline.convert_book")
    books = tmp_path / "books"
    books.mkdir()
    (books / "Novel.pdf").write_bytes(b"synthetic input")
    config = tmp_path / "config.toml"
    config.write_text('[tts.profiles."Novel"]\ntemperature = 0.25\n', encoding="utf-8")
    result = runner.invoke(
        app, ["batch", str(books), "--config", str(config), "--tts-temperature", "0.4", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert seen[0].tts.kitten.temperature == 0.4


def test_resynthesize_takes_the_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _capture(monkeypatch, "pdf2audiobook.pipeline.resynthesize_chapters")
    monkeypatch.setattr(
        "pdf2audiobook.cli.verify._manifest_chapters",
        lambda path: [types.SimpleNamespace(number=1, voice_id=None)],
    )
    manifest = tmp_path / "book" / "manifest.json"
    manifest.parent.mkdir()
    manifest.write_text("{}", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "resynthesize", str(manifest), "--chapter", "1", "--no-config",
            "--tts-temperature", "0.2", "--no-verify-audio", "--json",
        ],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert seen[0].tts.kitten.temperature == 0.2


def _config_show(*args: str, env: dict[str, str] | None = None) -> dict:
    result = runner.invoke(app, ["config", "show", *args, "--json"], env=env)
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_config_show_reports_a_set_temperature_as_unused_without_kitten_2() -> None:
    payload = _config_show("--no-config", env={ENV: "0.2"})
    assert payload["tts"]["kitten"]["temperature"] == 0.2
    assert "tts.kitten.temperature" in payload["_unused_settings"]


@pytest.mark.parametrize(
    "env",
    [{}, {ENV: "0.2", "PDF2AUDIOBOOK_TTS_MODEL": "kitten2"}],
    ids=["default", "kitten2"],
)
def test_config_show_does_not_flag_a_used_or_default_temperature(env: dict[str, str]) -> None:
    payload = _config_show("--no-config", env=env)
    assert "tts.kitten.temperature" not in payload.get("_unused_settings", [])


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, None),
        ({"PDF2AUDIOBOOK_TTS_MODEL": "kitten2"}, 0.2),
        ({"PDF2AUDIOBOOK_TTS_MODEL": "kitten2", ENV: "0.4"}, 0.4),
        ({"PDF2AUDIOBOOK_TTS_PROVIDER": "piper", ENV: "0.4"}, None),
    ],
    ids=["mini", "kitten2-default", "kitten2-set", "piper"],
)
def test_doctor_reports_the_temperature_only_for_kitten_2(
    env: dict[str, str], expected: float | None
) -> None:
    result = runner.invoke(app, ["doctor", "--no-config", "--json"], env=env)
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["tts_temperature"] == expected


def test_doctor_reports_the_temperature_without_reference_paths(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        '[tts.kitten]\nmodel = "kitten2"\ntemperature = 0.4\n'
        '[tts.voice_clone]\nreference_audio = "/PRIVATE/narrator.wav"\n'
        'reference_text_file = "/PRIVATE/narrator.txt"\n',
        encoding="utf-8",
    )
    result = runner.invoke(app, ["doctor", "--config", str(config), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["tts_temperature"] == 0.4
    assert "PRIVATE" not in result.stdout and "PRIVATE" not in result.stderr
