"""Commands that describe the setup or a book without changing anything."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import typer

from pdf2audiobook import __version__
from pdf2audiobook.cli._core import (
    CONVERSION_STATUS_MAX_BYTES,
    ClickExit,
    app,
    config_app,
    configure_effective_logging,
    emit,
    fail,
    fail_interrupted,
)
from pdf2audiobook.config import Settings, load_settings, settings_public
from pdf2audiobook.errors import (
    AudioError,
    InputError,
    LLMError,
)
from pdf2audiobook.logging import (
    set_output_mode,
)


@config_app.command("show", epilog="Example: pdf2audiobook config show --sources")
def show_config(
    config: Path | None = typer.Option(None, "--config"),
    no_config: bool = typer.Option(False, "--no-config"),
    sources: bool = typer.Option(False, "--sources"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    set_output_mode(json_output)
    try:
        settings, origin = load_settings(config, no_config=no_config)
        configure_effective_logging(settings, origin)
        payload = settings_public(settings)
        if origin.get("cache.directory", "built-in") != "built-in":
            payload["_unused_settings"] = ["cache.directory"]
        if sources:
            payload["_sources"] = origin
        emit(payload, json_output)
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


LLM_INSTRUCTIONS_ALLOWANCE = 4096


def _llm_capacity(settings: Settings) -> dict[str, Any]:
    """Content-free check of whether the configured LLM can take one analysis window."""
    if not settings.llm.enabled:
        return {"provider": "disabled", "checked": False}
    provider_name = settings.llm.provider
    if provider_name != "ollama":
        # Only Ollama reports the context it really serves.
        return {"provider": provider_name, "checked": False}
    from pdf2audiobook.llm.provider import create_provider

    needed = (
        settings.llm.chunk_tokens
        + settings.llm.max_output_tokens
        + 128
        + LLM_INSTRUCTIONS_ALLOWANCE
    )
    report: dict[str, Any] = {
        "provider": provider_name,
        "checked": True,
        "model": settings.llm.ollama.model,
        "configured_context": settings.llm.max_context_tokens,
        "output_tokens": settings.llm.max_output_tokens,
        "chunk_tokens": settings.llm.chunk_tokens,
        "estimated_tokens_needed": needed,
    }
    try:
        with create_provider(settings) as provider:
            served = provider._ollama_served_context(provider._model())
    except LLMError:
        return {**report, "reachable": False, "served_context": None, "enough": False}
    limit = min(served, settings.llm.max_context_tokens)
    return {**report, "reachable": True, "served_context": served, "enough": needed <= limit}


@app.command(epilog="Example: pdf2audiobook doctor --check-llm --json")
def doctor(
    json_output: bool = typer.Option(False, "--json"),
    config: Path | None = typer.Option(None, "--config"),
    no_config: bool = typer.Option(False, "--no-config"),
    check_llm: bool = typer.Option(
        False,
        "--check-llm",
        help="Also ask a local Ollama what context it serves (loads the model).",
    ),
) -> None:
    set_output_mode(json_output)
    try:
        settings, origins = load_settings(config, no_config=no_config)
        configure_effective_logging(settings, origins)
        from importlib.metadata import PackageNotFoundError, version

        try:
            version("kittenml")
            kitten_installed = True
        except PackageNotFoundError:
            kitten_installed = False
        from pdf2audiobook.pdf import missing_ocr_languages, tesseract_languages

        languages = tesseract_languages()
        from pdf2audiobook.tts.cloning import clone_diagnostics

        emit(
            {
                "voice_clone": clone_diagnostics(settings),
                "version": __version__,
                "ffmpeg": bool(shutil.which("ffmpeg")),
                "tesseract": bool(shutil.which("tesseract")),
                "ocr_requested_languages": settings.pdf.ocr_language,
                "ocr_installed_languages": languages,
                "ocr_missing_languages": missing_ocr_languages(
                    settings.pdf.ocr_language, languages
                ),
                "kitten_installed": kitten_installed,
                "piper_installed": bool(shutil.which("piper")),
                "llm_provider": settings.llm.provider if settings.llm.enabled else "disabled",
                "process_citations": settings.reading.process_citations,
                "process_equations": settings.reading.process_equations,
                "llm_timeout_seconds": (
                    getattr(settings.llm, settings.llm.provider.replace("-", "_")).timeout_seconds
                    if settings.llm.enabled
                    else None
                ),
                **({"llm_check": _llm_capacity(settings)} if check_llm else {}),
            },
            json_output,
        )
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


@app.command(epilog="Example: pdf2audiobook inspect ./book.pdf --json")
def inspect(
    source: Path = typer.Argument(..., help="PDF/EPUB book or previously generated manifest.json"),
    pdf_password_env: str | None = typer.Option(
        None, "--pdf-password-env", help="Name of environment variable containing PDF password."
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    set_output_mode(json_output)
    try:
        if source.suffix.lower() == ".json":
            from pdf2audiobook.workspace import read_manifest

            manifest = read_manifest(source)
            from pdf2audiobook.analysis_state import analyzed_with_llm
            from pdf2audiobook.document.structure import chapter_coverage_report

            payload = {
                "title": manifest.title,
                "source_path": manifest.source_path,
                "review_required": manifest.review_required,
                "review_acknowledged": manifest.review_acknowledged,
                "approved": manifest.approved,
                "chapters": [chapter.model_dump() for chapter in manifest.chapters],
                "warnings": manifest.warnings,
                "coverage": chapter_coverage_report(manifest),
                # How the book was last analyzed, so a caller can keep it (null if unknown).
                "analyzed_with_llm": analyzed_with_llm(source.parent),
            }
            from pdf2audiobook.jsonio import JSONTooLargeError, load_size_checked_json

            status_path = source.parent / "reports" / "conversion_status.json"
            try:
                conversion_status = load_size_checked_json(
                    status_path,
                    max_bytes=CONVERSION_STATUS_MAX_BYTES,
                    max_depth=16,
                )
            except JSONTooLargeError:
                raise InputError("Conversion status file exceeds safe size limit") from None
            if isinstance(conversion_status, dict):
                payload["conversion_status"] = conversion_status
        else:
            from pdf2audiobook.pdf import inspect_pdf

            payload = inspect_pdf(source, password_env=pdf_password_env)
        emit(payload, json_output)
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


@app.command(epilog="Example: pdf2audiobook workspace ./book.pdf --json")
def workspace(
    source: Path = typer.Argument(..., help="PDF or EPUB book."),
    output: Path | None = typer.Option(None, "--output", help="Folder that holds workspaces."),
    config: Path | None = typer.Option(None, "--config"),
    no_config: bool = typer.Option(False, "--no-config"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show the workspace folder analysis uses for a book, without creating it."""
    set_output_mode(json_output)
    try:
        from pdf2audiobook.pipeline import analysis_workspace_folder

        overrides = {"general": {"output_dir": str(output)}} if output is not None else None
        settings, origins = load_settings(config, no_config=no_config, overrides=overrides)
        configure_effective_logging(settings, origins)
        folder = analysis_workspace_folder(source, settings)
        emit({"workspace": str(folder), "exists": folder.is_dir()}, json_output)
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


@app.command(epilog="Example: pdf2audiobook voices --tts-provider kitten --json")
def voices(
    tts_provider: str | None = typer.Option(None, "--tts-provider"),
    tts_model: str | None = typer.Option(None, "--tts-model"),
    config: Path | None = typer.Option(None, "--config"),
    no_config: bool = typer.Option(False, "--no-config"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """List the voices the selected text-to-speech provider accepts."""
    set_output_mode(json_output)
    try:
        from pdf2audiobook.pipeline import create_tts_provider

        settings, origins = load_settings(config, no_config=no_config)
        name = tts_provider or settings.tts.provider
        tts: dict[str, Any] = {}
        if tts_provider is not None:
            tts["provider"] = tts_provider
        if tts_model is not None:
            key = "model_path" if name == "piper" else "model"
            tts.setdefault("piper" if name == "piper" else "kitten", {})[key] = tts_model
        if tts:
            settings, origins = load_settings(config, no_config=no_config, overrides={"tts": tts})
        configure_effective_logging(settings, origins)
        from pdf2audiobook.tts.cloning import clone_diagnostics

        if settings.tts.provider == "kitten":
            emit(_kitten_voice_catalog(settings), json_output)
            return
        provider = create_tts_provider(settings)
        # Piper speakers are numbers in the model, not names, so it has nothing to list.
        listable = getattr(provider, "supports_voice_listing", False) is True
        section = settings.tts.piper if settings.tts.provider == "piper" else settings.tts.kitten
        emit(
            {
                "provider": settings.tts.provider,
                "voices": provider.list_voices() if listable else [],
                "listable": listable,
                "default_voice": section.voice,
                "voice_clone": clone_diagnostics(settings),
            },
            json_output,
        )
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


def _kitten_voice_catalog(settings: Settings) -> dict[str, Any]:
    """Known models share eight original voices; discovery never initializes an SDK."""
    from importlib.metadata import PackageNotFoundError, version

    from pdf2audiobook.tts import KITTEN_BUILTIN_VOICES, KITTEN_MODEL_ALIASES
    from pdf2audiobook.tts.cloning import clone_diagnostics

    model = settings.tts.kitten.model
    if model not in {"kitten2", "KittenML/kitten-tts-2"}:
        try:
            version("kittenml")
        except PackageNotFoundError:
            raise AudioError(
                "Kitten TTS is not installed. Run 'uv sync --extra kitten' first."
            ) from None
    known = model in KITTEN_MODEL_ALIASES or model in KITTEN_MODEL_ALIASES.values()
    return {
        "provider": "kitten",
        "voices": list(KITTEN_BUILTIN_VOICES) if known else [],
        "listable": known,
        "default_voice": settings.tts.kitten.voice,
        "voice_clone": clone_diagnostics(settings),
    }


@app.command(epilog="Example: pdf2audiobook thumbnail ./book.pdf --output ./cover.png --json")
def thumbnail(
    source: Path = typer.Argument(..., help="PDF or EPUB book."),
    output: Path = typer.Option(..., "--output", help="PNG file to write."),
    width: int = typer.Option(320, "--width", min=16, max=2048, help="Width in pixels."),
    pdf_password_env: str | None = typer.Option(
        None, "--pdf-password-env", help="Name of environment variable containing PDF password."
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Render a book's first page (or an EPUB's cover) as a PNG thumbnail."""
    set_output_mode(json_output)
    try:
        from pdf2audiobook.pdf import render_thumbnail

        rendered_width, height = render_thumbnail(
            source, output, width=width, password_env=pdf_password_env
        )
        emit(
            {"thumbnail": str(output), "width": rendered_width, "height": height},
            json_output,
        )
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)
