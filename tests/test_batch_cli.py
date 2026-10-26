"""Directory batch conversion and per-book voice profile behavior."""

import json
from pathlib import Path

from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.config import Settings
from pdf2audiobook.pipeline import settings_for_book_tts


def test_named_tts_profile_is_applied_and_cli_settings_win():
    settings = Settings.model_validate(
        {
            "tts": {
                "profiles": {
                    "Story": {
                        "provider": "piper",
                        "piper_model_path": "/models/story.onnx",
                        "voice": "3",
                        "speed": 1.25,
                    }
                }
            }
        }
    )

    configured = settings_for_book_tts(settings, "Story")
    cli_override = settings_for_book_tts(settings, "Story", explicit=frozenset({"voice", "speed"}))

    assert configured.tts.provider == "piper"
    assert configured.tts.piper.model_path == "/models/story.onnx"
    assert configured.tts.piper.voice == "3"
    assert configured.tts.piper.speed == 1.25
    assert cli_override.tts.piper.voice == ""
    assert cli_override.tts.piper.speed == 1.0


def test_batch_converts_sorted_pdfs_and_applies_matching_profile(tmp_path, monkeypatch):
    books = tmp_path / "books"
    books.mkdir()
    (books / "zeta.pdf").write_bytes(b"fixture")
    (books / "Alpha.PDF").write_bytes(b"fixture")
    nested = books / "nested"
    nested.mkdir()
    (nested / "ignored.pdf").write_bytes(b"fixture")
    config = tmp_path / "config.toml"
    config.write_text(
        '[tts.profiles."Alpha"]\nprovider = "piper"\n'
        'piper_model_path = "/models/alpha.onnx"\nvoice = "2"\nspeed = 1.1\n',
        encoding="utf-8",
    )
    seen = []

    def convert(source: Path, settings: Settings):
        seen.append((source.name, settings.tts.provider, settings.tts.piper.model_path))
        return [Path(f"{source.stem}.mp3")]

    monkeypatch.setattr("pdf2audiobook.pipeline.convert_book", convert)
    result = CliRunner().invoke(app, ["batch", str(books), "--config", str(config), "--json"])

    assert result.exit_code == 0, result.output
    assert [row[0] for row in seen] == ["Alpha.PDF", "zeta.pdf"]
    assert seen[0][1:] == ("piper", "/models/alpha.onnx")
    payload = json.loads(result.stdout)
    assert payload["failed"] == 0
    assert [book["book"] for book in payload["books"]] == ["Alpha.PDF", "zeta.pdf"]


def test_batch_cli_tts_options_override_per_book_profile(tmp_path, monkeypatch):
    books = tmp_path / "books"
    books.mkdir()
    (books / "Story.pdf").write_bytes(b"fixture")
    config = tmp_path / "settings.toml"
    config.write_text(
        '[tts.profiles.Story]\nprovider="piper"\npiper_model_path="profile.onnx"\n'
        'voice="1"\nspeed=1.0\n',
        encoding="utf-8",
    )
    seen = []

    def convert(_source: Path, settings: Settings):
        seen.append(settings)
        return []

    monkeypatch.setattr("pdf2audiobook.pipeline.convert_book", convert)
    result = CliRunner().invoke(
        app,
        [
            "batch",
            str(books),
            "--config",
            str(config),
            "--tts-model",
            "cli.onnx",
            "--voice",
            "3",
            "--speed",
            "1.5",
            "--sample-rate",
            "22050",
            "--bitrate",
            "96k",
        ],
    )
    assert result.exit_code == 0, result.output
    settings = seen[0]
    assert settings.tts.provider == "piper"
    assert settings.tts.piper.model_path == "cli.onnx"
    assert settings.tts.piper.voice == "3"
    assert settings.tts.piper.speed == 1.5
    assert settings.tts.sample_rate == 22050
    assert settings.tts.bitrate == "96k"


def test_invalid_batch_profile_exits_before_converting_any_book(tmp_path, monkeypatch):
    books = tmp_path / "books"
    books.mkdir()
    (books / "Story.pdf").write_bytes(b"fixture")
    config = tmp_path / "settings.toml"
    config.write_text("[tts.profiles.Story]\nspeed = 99.0\n", encoding="utf-8")
    called = []
    monkeypatch.setattr(
        "pdf2audiobook.pipeline.convert_book", lambda *_args, **_kwargs: called.append(True)
    )

    result = CliRunner().invoke(app, ["batch", str(books), "--config", str(config), "--json"])

    assert result.exit_code == 2
    assert called == []
