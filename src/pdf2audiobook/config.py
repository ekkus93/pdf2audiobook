"""Strict TOML settings and source-aware CLI/environment overrides."""
from __future__ import annotations

import json
import os
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pdf2audiobook.errors import ConfigError


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class General(ConfigModel):
    output_dir: str = "./audiobooks"
    resume: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class Pdf(ConfigModel):
    ocr: Literal["auto", "always", "never"] = "auto"
    ocr_language: str = "eng"
    password_env: str | None = None
    ocr_dpi: int = Field(default=300, ge=72, le=600)
    remove_page_numbers: bool = True
    remove_headers: bool = True
    remove_footers: bool = True
    footnotes: Literal["warn", "inline", "omit"] = "warn"


class Chapters(ConfigModel):
    min_boundary_confidence: float = Field(default=0.75, ge=0, le=1)
    allow_single_chapter: bool = False


class RemoteLLM(ConfigModel):
    model: str
    base_url: str | None = None
    api_key_env: str | None = None


class LLM(ConfigModel):
    enabled: bool = True
    provider: Literal["openai", "ollama", "llama-server"] = "ollama"
    temperature: float = Field(default=0.1, ge=0, le=2)
    max_context_tokens: int = Field(default=16384, ge=512)
    chunk_tokens: int = Field(default=4000, ge=100)
    max_retries: int = Field(default=3, ge=0, le=15)
    structure: bool = True
    cleanup: bool = True
    classification: bool = True
    narration: bool = True
    allow_remote_content: bool = False
    openai: RemoteLLM = Field(
        default_factory=lambda: RemoteLLM(model="gpt-4.1-mini", api_key_env="OPENAI_API_KEY")
    )
    ollama: RemoteLLM = Field(
        default_factory=lambda: RemoteLLM(
            model="qwen3.5:9b", base_url="http://127.0.0.1:11434/v1"
        )
    )
    llama_server: RemoteLLM = Field(
        default_factory=lambda: RemoteLLM(
            model="auto", base_url="http://127.0.0.1:8080/v1",
            api_key_env="LLAMA_SERVER_API_KEY"
        )
    )


class TTSModel(ConfigModel):
    model: str = "mini"
    voice: str = "Jasper"
    speed: float = Field(default=1.0, gt=0, le=3)


class TTS(ConfigModel):
    provider: Literal["kitten"] = "kitten"
    output_format: Literal["mp3"] = "mp3"
    bitrate: str = "128k"
    sample_rate: int = Field(default=24000, ge=8000, le=96000)
    pause_ms: int = Field(default=250, ge=0, le=5000)
    kitten: TTSModel = Field(default_factory=TTSModel)


class Cache(ConfigModel):
    enabled: bool = True
    directory: str = "~/.cache/pdf2audiobook"


class Settings(ConfigModel):
    general: General = Field(default_factory=General)
    pdf: Pdf = Field(default_factory=Pdf)
    chapters: Chapters = Field(default_factory=Chapters)
    llm: LLM = Field(default_factory=LLM)
    tts: TTS = Field(default_factory=TTS)
    cache: Cache = Field(default_factory=Cache)


ENV_KEYS = {
    "PDF2AUDIOBOOK_OUTPUT_DIR": ("general", "output_dir"),
    "PDF2AUDIOBOOK_RESUME": ("general", "resume"),
    "PDF2AUDIOBOOK_OCR": ("pdf", "ocr"),
    "PDF2AUDIOBOOK_OCR_LANGUAGE": ("pdf", "ocr_language"),
    "PDF2AUDIOBOOK_PDF_PASSWORD_ENV": ("pdf", "password_env"),
    "PDF2AUDIOBOOK_OCR_DPI": ("pdf", "ocr_dpi"),
    "PDF2AUDIOBOOK_LLM_ENABLED": ("llm", "enabled"),
    "PDF2AUDIOBOOK_LLM_PROVIDER": ("llm", "provider"),
    "PDF2AUDIOBOOK_LLM_MODEL": ("llm", "@selected", "model"),
    "PDF2AUDIOBOOK_LLM_URL": ("llm", "@selected", "base_url"),
    "PDF2AUDIOBOOK_ALLOW_REMOTE_CONTENT": ("llm", "allow_remote_content"),
    "PDF2AUDIOBOOK_TTS_VOICE": ("tts", "kitten", "voice"),
    "PDF2AUDIOBOOK_TTS_MODEL": ("tts", "kitten", "model"),
}


def user_config_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / (
        "pdf2audiobook/config.toml"
    )


def _apply(obj: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    for part in path[:-1]:
        obj = obj.setdefault(part, {})
    obj[path[-1]] = value


def _flatten(obj: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    result = {}
    for key, value in obj.items():
        if isinstance(value, dict):
            result.update(_flatten(value, prefix + key + "."))
        else:
            result[prefix + key] = value
    return result


def _merge(base: dict[str, Any], extra: dict[str, Any]) -> None:
    for key, value in extra.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _merge(base[key], value)
        else:
            base[key] = deepcopy(value)


def _parse_env(value: str) -> Any:
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value


def load_settings(
    config_path: Path | None = None,
    *,
    no_config: bool = False,
    overrides: dict[str, Any] | None = None,
    environ: dict[str, str] | None = None,
) -> tuple[Settings, dict[str, str]]:
    if no_config and config_path is not None:
        raise ConfigError("--config conflicts with --no-config")
    data = Settings().model_dump()
    sources = {key: "built-in" for key in _flatten(data)}
    path = config_path or user_config_path()
    if config_path is not None and not path.is_file() and not no_config:
        raise ConfigError(f"configuration file not found: {path}")
    if not no_config and path.exists():
        try:
            toml = tomllib.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise ConfigError(f"cannot read {path}: {exc}") from exc
        _merge(data, toml)
        sources.update({key: f"file:{path}" for key in _flatten(toml)})
    env = environ if environ is not None else os.environ
    selected = (overrides or {}).get("llm", {}).get(
        "provider", env.get("PDF2AUDIOBOOK_LLM_PROVIDER", data["llm"]["provider"])
    )
    selected = str(selected).replace("-", "_")
    for env_name, setting_path in ENV_KEYS.items():
        if env_name in env:
            actual = tuple(selected if key == "@selected" else key for key in setting_path)
            _apply(data, actual, _parse_env(env[env_name]))
            sources[".".join(actual)] = f"env:{env_name}"
    if overrides:
        _merge(data, overrides)
        sources.update({key: "CLI" for key in _flatten(overrides)})
    try:
        result = Settings.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration: {exc}") from exc
    if result.llm.chunk_tokens >= result.llm.max_context_tokens:
        raise ConfigError("llm.chunk_tokens must be smaller than llm.max_context_tokens")
    return result, sources


def settings_public(settings: Settings) -> dict[str, Any]:
    # Stored provider credentials are names of environment variables, never secret values.
    return settings.model_dump()
