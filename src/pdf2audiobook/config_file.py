"""Create an editable configuration without replacing an existing file."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from pdf2audiobook.config import Settings, user_config_path
from pdf2audiobook.errors import ConfigError

# Omit settings whose explicit presence changes behavior, such as log_level and
# process_equations (the latter must remain inactive with --no-llm).
_DEFAULT_FIELDS = {
    "general": ("output_dir", "resume", "progress"),
    "pdf": ("ocr", "ocr_language", "footnotes", "figure_text"),
    "llm": ("enabled", "provider", "allow_remote_content"),
    "llm.ollama": ("model", "base_url"),
    "tts": ("provider", "bitrate", "sample_rate"),
    "tts.voice_clone": ("enabled",),
    "tts.kitten": ("model", "voice", "speed"),
    "reading": ("process_citations",),
}


def default_config_text() -> str:
    """Render common built-in defaults, never environment values or credentials."""
    defaults = Settings().model_dump()
    lines = [
        "# pdf2audiobook configuration",
        "# Only changed settings need to be present. See: pdf2audiobook config show --sources",
        "# LLM assistance uses local Ollama; use --no-llm to convert without it.",
        "# Keep API keys and PDF passwords in environment variables, not in this file.",
    ]
    for section, fields in _DEFAULT_FIELDS.items():
        values = defaults
        for name in section.split("."):
            values = values[name]
        lines.extend(("", f"[{section}]"))
        lines.extend(f"{name} = {json.dumps(values[name], ensure_ascii=False)}" for name in fields)
    return "\n".join(lines) + "\n"


def initialize_config(config: Path | None = None) -> tuple[Path, bool]:
    """Publish a complete private file atomically; an existing path is never changed."""
    path = (config if config is not None else user_config_path()).expanduser().absolute()
    try:
        # lexists also recognizes dangling symlinks, which must not be replaced.
        if os.path.lexists(path):
            return path, False
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent) as draft:
            draft.write(default_config_text().encode("utf-8"))
            draft.flush()
            os.fsync(draft.fileno())
            try:
                os.link(draft.name, path)
            except FileExistsError:
                return path, False
    except OSError:
        raise ConfigError(
            "Could not create configuration; check the folder and permissions"
        ) from None
    return path, True
