"""Strict TOML settings and source-aware CLI/environment overrides."""

from __future__ import annotations

import json
import os
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from pdf2audiobook.errors import ConfigError


class ConfigModel(BaseModel):
    # NaN/Infinity must not disable token-cost and price validation or emit
    # nonstandard JSON in persisted budget reports.
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


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
    footnotes: Literal["warn", "inline", "end", "omit"] = "warn"


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
    max_output_tokens: int = Field(default=1024, ge=1)
    chunk_tokens: int = Field(default=4000, ge=100)
    max_retries: int = Field(default=3, ge=0, le=15)
    max_requests: int | None = Field(default=None, ge=1)
    max_reported_tokens: int | None = Field(default=None, ge=1)
    max_estimated_cost_usd: float | None = Field(default=None, gt=0)
    input_cost_usd_per_million_tokens: float | None = Field(default=None, ge=0)
    output_cost_usd_per_million_tokens: float | None = Field(default=None, ge=0)
    structure: bool = True
    contents: bool = False
    cleanup: bool = True
    classification: bool = True
    narration: bool = True
    vision: bool = False
    allow_remote_content: bool = False
    fallback_to_deterministic: bool = False
    openai: RemoteLLM = Field(
        default_factory=lambda: RemoteLLM(model="gpt-4.1-mini", api_key_env="OPENAI_API_KEY")
    )
    ollama: RemoteLLM = Field(
        default_factory=lambda: RemoteLLM(model="qwen3.5:9b", base_url="http://127.0.0.1:11434/v1")
    )
    llama_server: RemoteLLM = Field(
        default_factory=lambda: RemoteLLM(
            model="auto", base_url="http://127.0.0.1:8080/v1", api_key_env="LLAMA_SERVER_API_KEY"
        )
    )


class TTSModel(ConfigModel):
    model: str = "mini"
    voice: str = "Jasper"
    speed: float = Field(default=1.0, gt=0, le=3)


class PiperTTSModel(ConfigModel):
    model_path: str = ""
    voice: str = ""
    speed: float = Field(default=1.0, gt=0, le=3)

    @field_validator("voice")
    @classmethod
    def validate_speaker_id(cls, value: str) -> str:
        if value and (not value.isdecimal() or len(value) > 10):
            raise ValueError("Piper voice must be a nonnegative decimal speaker ID")
        return value


class TTSProfile(ConfigModel):
    provider: Literal["kitten", "piper"] | None = None
    kitten_model: str | None = None
    piper_model_path: str | None = None
    voice: str | None = None
    speed: float | None = Field(default=None, gt=0, le=3)

    @model_validator(mode="after")
    def validate_piper_profile(self) -> TTSProfile:
        if (
            self.provider == "piper"
            and self.voice is not None
            and (not self.voice.isdecimal() or len(self.voice) > 10)
        ):
            raise ValueError("Piper profile voice must be a decimal speaker ID")
        return self


class TTS(ConfigModel):
    provider: Literal["kitten", "piper"] = "kitten"
    output_format: Literal["mp3"] = "mp3"
    bitrate: str = "128k"
    sample_rate: int = Field(default=24000, ge=8000, le=96000)
    pause_ms: int = Field(default=250, ge=0, le=5000)
    max_retries: int = Field(default=2, ge=0, le=10)
    kitten: TTSModel = Field(default_factory=TTSModel)
    piper: PiperTTSModel = Field(default_factory=PiperTTSModel)
    profiles: dict[str, TTSProfile] = Field(default_factory=dict)
    pronunciations: dict[str, str] = Field(default_factory=dict)

    @field_validator("sample_rate")
    @classmethod
    def validate_sample_rate(cls, value: int) -> int:
        if value not in {8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000}:
            raise ValueError("sample_rate must be supported by MPEG audio")
        return value

    @field_validator("pronunciations")
    @classmethod
    def validate_pronunciations(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 10_000:
            raise ValueError("at most 10000 pronunciation entries are supported")
        normalized: dict[str, str] = {}
        edge = "\"'()[]{}<>“”‘’"
        for source, spoken in value.items():
            source_key = source if isinstance(source, str) else ""
            key = source_key.strip(edge).rstrip(",;:!?…").casefold()
            if (
                not key
                or len(source_key) > 64
                or any(char.isspace() for char in source_key)
                or "[[" in source_key
                or "]]" in source_key
                or not isinstance(spoken, str)
                or not spoken.strip()
                or len(spoken) > 80
                or any(char.isspace() for char in spoken)
            ):
                raise ValueError(
                    "pronunciation keys must be nonempty, whitespace-free and at most 64 characters; values must be one word"
                )
            if key in normalized:
                raise ValueError("pronunciation keys must be unique ignoring case")
            normalized[key] = spoken.strip()
        return normalized


class Cache(ConfigModel):
    enabled: bool = True
    directory: str = "~/.cache/pdf2audiobook"


class Audio(ConfigModel):
    cover_image: str | None = None


class Settings(ConfigModel):
    general: General = Field(default_factory=General)
    pdf: Pdf = Field(default_factory=Pdf)
    chapters: Chapters = Field(default_factory=Chapters)
    llm: LLM = Field(default_factory=LLM)
    tts: TTS = Field(default_factory=TTS)
    cache: Cache = Field(default_factory=Cache)
    audio: Audio = Field(default_factory=Audio)


ENV_KEYS = {
    "PDF2AUDIOBOOK_OUTPUT_DIR": ("general", "output_dir"),
    "PDF2AUDIOBOOK_RESUME": ("general", "resume"),
    "PDF2AUDIOBOOK_OCR": ("pdf", "ocr"),
    "PDF2AUDIOBOOK_OCR_LANGUAGE": ("pdf", "ocr_language"),
    "PDF2AUDIOBOOK_PDF_PASSWORD_ENV": ("pdf", "password_env"),
    "PDF2AUDIOBOOK_OCR_DPI": ("pdf", "ocr_dpi"),
    "PDF2AUDIOBOOK_LLM_ENABLED": ("llm", "enabled"),
    "PDF2AUDIOBOOK_LLM_VISION": ("llm", "vision"),
    "PDF2AUDIOBOOK_LLM_CONTENTS": ("llm", "contents"),
    "PDF2AUDIOBOOK_LLM_PROVIDER": ("llm", "provider"),
    "PDF2AUDIOBOOK_LLM_MAX_REQUESTS": ("llm", "max_requests"),
    "PDF2AUDIOBOOK_LLM_MAX_OUTPUT_TOKENS": ("llm", "max_output_tokens"),
    "PDF2AUDIOBOOK_LLM_MAX_REPORTED_TOKENS": ("llm", "max_reported_tokens"),
    "PDF2AUDIOBOOK_LLM_MAX_ESTIMATED_COST_USD": ("llm", "max_estimated_cost_usd"),
    "PDF2AUDIOBOOK_LLM_INPUT_COST_USD_PER_MILLION_TOKENS": (
        "llm",
        "input_cost_usd_per_million_tokens",
    ),
    "PDF2AUDIOBOOK_LLM_OUTPUT_COST_USD_PER_MILLION_TOKENS": (
        "llm",
        "output_cost_usd_per_million_tokens",
    ),
    "PDF2AUDIOBOOK_LLM_MODEL": ("llm", "@selected", "model"),
    "PDF2AUDIOBOOK_LLM_URL": ("llm", "@selected", "base_url"),
    "PDF2AUDIOBOOK_ALLOW_REMOTE_CONTENT": ("llm", "allow_remote_content"),
    "PDF2AUDIOBOOK_LLM_FALLBACK_TO_DETERMINISTIC": ("llm", "fallback_to_deterministic"),
    "PDF2AUDIOBOOK_TTS_PROVIDER": ("tts", "provider"),
    "PDF2AUDIOBOOK_TTS_MODEL": ("tts", "@selected", "model"),
    "PDF2AUDIOBOOK_TTS_VOICE": ("tts", "@selected", "voice"),
    "PDF2AUDIOBOOK_TTS_SPEED": ("tts", "@selected", "speed"),
    "PDF2AUDIOBOOK_TTS_SAMPLE_RATE": ("tts", "sample_rate"),
    "PDF2AUDIOBOOK_TTS_BITRATE": ("tts", "bitrate"),
    "PDF2AUDIOBOOK_TTS_MAX_RETRIES": ("tts", "max_retries"),
    "PDF2AUDIOBOOK_TTS_PIPER_MODEL_PATH": ("tts", "piper", "model_path"),
    "PDF2AUDIOBOOK_TTS_PIPER_VOICE": ("tts", "piper", "voice"),
    "PDF2AUDIOBOOK_TTS_PIPER_SPEED": ("tts", "piper", "speed"),
}


def user_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    if not base.is_absolute():
        base = Path.home() / ".config"
    return base / "pdf2audiobook/config.toml"


def _apply(obj: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    for part in path[:-1]:
        child = obj.setdefault(part, {})
        if not isinstance(child, dict):
            raise ConfigError("invalid configuration values; check field names and types")
        obj = child
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


def _parse_env(value: str, current: Any) -> Any:
    if isinstance(current, str) or current is None:
        return value
    if isinstance(current, bool):
        normalized = value.casefold()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
        return value
    if isinstance(current, (int, float)) and not isinstance(current, bool):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return value
        return (
            parsed if isinstance(parsed, (int, float)) and not isinstance(parsed, bool) else value
        )
    if isinstance(current, (dict, list)):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return value
        return parsed if isinstance(parsed, type(current)) else value
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
    # Reject non-mapping CLI data before merge or provider selection: arbitrary
    # caller input must not trigger raw Python errors with private values.
    if overrides is not None and not isinstance(overrides, dict):
        raise ConfigError("invalid configuration values; check field names and types")
    data = Settings().model_dump()
    sources = {key: "built-in" for key in _flatten(data)}
    path = config_path or user_config_path()
    if config_path is not None and not path.is_file() and not no_config:
        raise ConfigError("configuration file not found; check --config path")
    if not no_config and path.exists():
        try:
            toml = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            # TOML parser diagnostics may contain configuration values or paths.
            raise ConfigError("invalid TOML configuration syntax") from None
        except (OSError, UnicodeError):
            raise ConfigError(
                "cannot read configuration file; check permissions and encoding"
            ) from None
        if any(
            key in toml and not isinstance(toml[key], dict)
            for key in ("general", "pdf", "chapters", "llm", "tts", "cache", "audio")
        ):
            raise ConfigError("invalid configuration values; check field names and types")
        _merge(data, toml)
        sources.update({key: f"file:{path}" for key in _flatten(toml)})
    env = environ if environ is not None else os.environ
    # TOML permits a scalar in place of [llm]; similarly untrusted CLI
    # overrides may supply a list or scalar. Validate both before .get().
    llm_data = data.get("llm")
    llm_overrides = (overrides or {}).get("llm", {})
    if not isinstance(llm_data, dict) or not isinstance(llm_overrides, dict):
        raise ConfigError("invalid configuration values; check field names and types")
    selected = llm_overrides.get(
        "provider", env.get("PDF2AUDIOBOOK_LLM_PROVIDER", llm_data["provider"])
    )
    selected = str(selected).replace("-", "_")
    tts_data = data.get("tts")
    tts_overrides = (overrides or {}).get("tts", {})
    if not isinstance(tts_data, dict) or not isinstance(tts_overrides, dict):
        raise ConfigError("invalid configuration values; check field names and types")
    tts_provider = tts_overrides.get(
        "provider", env.get("PDF2AUDIOBOOK_TTS_PROVIDER", tts_data["provider"])
    )
    tts_provider = str(tts_provider)
    for env_name, setting_path in ENV_KEYS.items():
        if env_name in env:
            if setting_path[0] == "tts" and "@selected" in setting_path:
                actual = tuple(tts_provider if key == "@selected" else key for key in setting_path)
                if env_name == "PDF2AUDIOBOOK_TTS_MODEL" and tts_provider == "piper":
                    actual = ("tts", "piper", "model_path")
            else:
                actual = tuple(selected if key == "@selected" else key for key in setting_path)
            current: Any = data
            for part in actual:
                current = current.get(part) if isinstance(current, dict) else None
            _apply(data, actual, _parse_env(env[env_name], current))
            sources[".".join(actual)] = f"env:{env_name}"
    if overrides:
        _merge(data, overrides)
        sources.update({key: "CLI" for key in _flatten(overrides)})
    try:
        result = Settings.model_validate(data)
    except ValidationError:
        # Pydantic errors can echo rejected values, including provider URLs and secrets.
        raise ConfigError("invalid configuration values; check field names and types") from None
    result.general.output_dir = str(Path(result.general.output_dir).expanduser().resolve())
    if result.llm.max_estimated_cost_usd is not None and (
        result.llm.input_cost_usd_per_million_tokens is None
        or result.llm.output_cost_usd_per_million_tokens is None
    ):
        raise ConfigError("max_estimated_cost_usd requires explicit input/output token prices")
    if result.llm.chunk_tokens >= result.llm.max_context_tokens:
        raise ConfigError("llm.chunk_tokens must be smaller than llm.max_context_tokens")
    if result.llm.max_output_tokens + 128 >= result.llm.max_context_tokens:
        raise ConfigError("llm.max_output_tokens leaves no context room for messages")
    from pdf2audiobook.logging import configure_from_settings

    configure_from_settings(
        result.general.log_level,
        cache_directory_configured=sources.get("cache.directory", "built-in") != "built-in",
        explicit=sources.get("general.log_level", "built-in") != "built-in",
    )
    return result, sources


def _secret_field_paths(model: type[BaseModel], prefix: str = "") -> frozenset[str]:
    """Dotted paths of fields declared ``json_schema_extra={"secret": True}``."""
    paths: set[str] = set()
    for name, field in model.model_fields.items():
        path = f"{prefix}.{name}" if prefix else name
        extra = field.json_schema_extra
        if isinstance(extra, dict) and extra.get("secret") is True:
            paths.add(path)
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            paths |= _secret_field_paths(annotation, path)
    return frozenset(paths)


# Credentials are read from environment variables named in the settings, so no
# setting currently holds a secret value; a field that does must be marked.
_SECRET_CONFIG_PATHS = _secret_field_paths(Settings)


def settings_public(settings: Settings) -> dict[str, Any]:
    # Secret fields are explicitly listed; arbitrary user dictionary keys remain data.
    return _redact_public_value(settings.model_dump())


def _redact_public_value(value: Any, field_name: str = "", _path: str = "") -> Any:
    """Redact only declared secret fields and URL credential components."""
    if _path in _SECRET_CONFIG_PATHS and value is not None:
        return "***"
    if isinstance(value, dict):
        return {
            key: _redact_public_value(item, str(key), f"{_path}.{key}".strip("."))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_public_value(item, field_name, _path) for item in value]
    if isinstance(value, str) and "://" in value:
        authority_start = value.find("://") + 3
        userinfo_end = value.rfind("@")
        if userinfo_end >= authority_start:
            value = value[:authority_start] + "***@" + value[userinfo_end + 1 :]
        try:
            parsed = urlsplit(value)
        except ValueError:
            return "***"
        if not parsed.scheme or not parsed.netloc:
            return "***"
        netloc = parsed.netloc
        if "@" in netloc:
            netloc = "***@" + netloc.rsplit("@", 1)[1]
        query = "***" if parsed.query else ""
        fragment = "***" if parsed.fragment else ""
        return urlunsplit((parsed.scheme, netloc, parsed.path, query, fragment))
    return value
