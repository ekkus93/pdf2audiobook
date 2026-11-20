"""Offline model discovery and explicit pinned KittenTTS 2 downloads."""

import typer

from pdf2audiobook.cli._core import ClickExit, console, emit, fail, fail_interrupted, tts_app
from pdf2audiobook.errors import ConfigError
from pdf2audiobook.logging import set_output_mode
from pdf2audiobook.tts import KITTEN_MODEL_ALIASES
from pdf2audiobook.tts.catalog import fetch_model, missing_files, model_readiness


@tts_app.command("models", epilog="Example: pdf2audiobook tts models --json")
def tts_models(json_output: bool = typer.Option(False, "--json")) -> None:
    """List model capabilities and setup readiness without loading speech models."""
    set_output_mode(json_output)
    try:
        payload = {
            "models": [
                {"name": name, "model_id": model, "cloning": False}
                for name, model in KITTEN_MODEL_ALIASES.items()
                if name != "kitten2"
            ]
            + [model_readiness()]
        }
        emit(payload, json_output)
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


@tts_app.command("fetch", epilog="Example: pdf2audiobook tts fetch kitten2 --yes --json")
def tts_fetch(
    model: str = typer.Argument(..., help="kitten2 (the full cloning-capable model)."),
    yes: bool = typer.Option(False, "--yes", help="Download after reviewing the setup plan."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Fetch pinned artifacts explicitly, verifying checksums before publication."""
    set_output_mode(json_output)
    try:
        if model != "kitten2":
            raise ConfigError("Choose kitten2; legacy model setup is unchanged")
        plan = missing_files()
        if plan and not yes:
            if json_output:
                raise ConfigError("Review 'tts models --json', then pass --yes to fetch")
            ready = model_readiness()
            console.print(f"Download {ready['download_bytes']:,} bytes to {ready['directory']}")
            for artifact in plan:
                console.print(
                    f"{artifact['repo']}@{artifact['revision']}: {artifact['name']} ({artifact['size']:,} bytes)"
                )
            if not typer.confirm("Download these model files?", default=False, err=True):
                raise typer.Exit(1)
        downloaded = fetch_model(
            on_file=None
            if json_output
            else lambda item: console.print(f"Downloading {item['name']}")
        )
        emit({"model": model_readiness(), "fetched": downloaded}, json_output)
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)
