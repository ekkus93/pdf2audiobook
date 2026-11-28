"""The models an LLM server serves, for choosing one (the desktop app's Model field).

Only the server's model list is requested: no book content is sent, and an unreachable server
is a content-free `llm_unreachable` error.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from pdf2audiobook.cli._core import ClickExit, emit, fail, fail_interrupted, llm_app
from pdf2audiobook.config import load_settings
from pdf2audiobook.logging import set_output_mode

PROVIDERS = ("ollama", "llama-server", "openai")


def model_overrides(provider: str | None, url: str | None) -> dict[str, Any]:
    """Settings overrides: the LLM on, and the provider and server asked for."""
    llm: dict[str, Any] = {"enabled": True}
    if provider is not None:
        llm["provider"] = provider
    if url is not None:
        section = (provider or "ollama").replace("-", "_")
        llm[section] = {"base_url": url}
    return {"llm": llm}


@llm_app.command("models", epilog="Example: pdf2audiobook llm models --json")
def llm_models(
    llm_provider: str | None = typer.Option(
        None, "--llm-provider", help="ollama, llama-server or openai; default: the configured one."
    ),
    llm_url: str | None = typer.Option(None, "--llm-url", help="The server's API base URL."),
    allow_remote_content: bool = typer.Option(
        False, "--allow-remote-content", help="Needed for OpenAI, as for analysis."
    ),
    config: Path | None = typer.Option(None, "--config"),
    no_config: bool = typer.Option(False, "--no-config"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """List the models the LLM server serves, and the one the configuration names."""
    set_output_mode(json_output)
    try:
        from pdf2audiobook.errors import ConfigError
        from pdf2audiobook.llm.provider import create_provider

        if llm_provider is not None and llm_provider not in PROVIDERS:
            raise ConfigError("Choose ollama, llama-server or openai")
        overrides = model_overrides(llm_provider, llm_url)
        if allow_remote_content:
            overrides["llm"]["allow_remote_content"] = True
        settings, _origins = load_settings(config, no_config=no_config, overrides=overrides)
        selected = settings.llm.provider
        configured = getattr(settings.llm, selected.replace("-", "_")).model
        with create_provider(settings) as provider:
            models = provider.list_models()
        emit({"provider": selected, "configured": configured, "models": models}, json_output)
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)
