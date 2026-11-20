"""Configuration file initialization and validation."""

from pathlib import Path

import typer

from pdf2audiobook.cli._core import ClickExit, config_app, emit, fail, fail_interrupted
from pdf2audiobook.config import load_settings
from pdf2audiobook.config_file import initialize_config
from pdf2audiobook.logging import set_output_mode


@config_app.command("init", epilog="Example: pdf2audiobook config init --config ./config.toml")
def init_config(
    config: Path | None = typer.Option(None, "--config", help="Use this configuration file."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Create a file of common defaults; preserve any existing file."""
    set_output_mode(json_output)
    try:
        path, created = initialize_config(config)
        emit({"path": str(path), "created": created}, json_output)
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


@config_app.command(
    "validate", epilog="Example: pdf2audiobook config validate --config ./config.toml"
)
def validate_config(
    config: Path = typer.Option(..., "--config", help="The TOML file to validate."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Validate a file independently of environment overrides, without running providers."""
    set_output_mode(json_output)
    try:
        settings, _ = load_settings(config, environ={})
        from pdf2audiobook.tts.cloning import validate_clone_selection

        validate_clone_selection(settings)
        emit({"valid": True}, json_output)
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)
