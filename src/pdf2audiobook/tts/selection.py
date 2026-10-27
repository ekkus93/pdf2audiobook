"""TTS profile selection and reproducible model identities."""

from __future__ import annotations

from functools import lru_cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path

from pdf2audiobook.config import Settings
from pdf2audiobook.models import Chapter
from pdf2audiobook.tts import KITTEN_MODEL_ALIASES
from pdf2audiobook.workspace import digest_file, fingerprint


@lru_cache(maxsize=128)
def _model_file_digest(path: str, size: int, mtime_ns: int) -> str:
    """Memoize local model hashes while still invalidating changed file metadata."""
    del size, mtime_ns
    return digest_file(Path(path))


def _tts_model_identity(settings: Settings) -> str:
    """Return content/version identity for the active TTS model without loading it."""
    if settings.tts.provider == "piper":
        configured = settings.tts.piper.model_path
        if not configured:
            return fingerprint("piper-model-v1", "missing")
        model_path = Path(configured).expanduser().resolve()
        digests = []
        for path in (model_path, Path(f"{model_path}.json")):
            try:
                stat = path.stat()
                digest = _model_file_digest(str(path), stat.st_size, stat.st_mtime_ns)
            except OSError:
                digest = "missing"
            digests.append((path.suffix, digest))
        return fingerprint("piper-model-v1", str(model_path), digests)
    model = settings.tts.kitten.model
    resolved_model = KITTEN_MODEL_ALIASES.get(model, model)
    try:
        engine_version = package_version("kittenml")
    except PackageNotFoundError:
        engine_version = "not-installed"
    return fingerprint("kitten-model-v1", resolved_model, engine_version)


def settings_for_book_tts(
    settings: Settings, book_stem: str, *, explicit: frozenset[str] = frozenset()
) -> Settings:
    """Apply a named TTS profile unless a command-line option overrides it."""
    profile = settings.tts.profiles.get(book_stem)
    if profile is None:
        return settings
    selected = settings.model_copy(deep=True)
    if "tts_provider" not in explicit and profile.provider is not None:
        selected.tts.provider = profile.provider
    if "tts_model" not in explicit:
        if profile.kitten_model is not None:
            selected.tts.kitten.model = profile.kitten_model
        if profile.piper_model_path is not None:
            selected.tts.piper.model_path = profile.piper_model_path
    if "voice" not in explicit and profile.voice is not None:
        if selected.tts.provider == "piper":
            selected.tts.piper.voice = profile.voice
        else:
            selected.tts.kitten.voice = profile.voice
    if "speed" not in explicit and profile.speed is not None:
        if selected.tts.provider == "piper":
            selected.tts.piper.speed = profile.speed
        else:
            selected.tts.kitten.speed = profile.speed
    return selected


def tts_selection(
    settings: Settings,
    chapter: Chapter | None = None,
    *,
    provider: str | None = None,
) -> tuple[str, str, float]:
    """Select the effective provider, voice and speed for one chapter or CLI request."""
    provider_name = provider or settings.tts.provider
    provider_settings = getattr(settings.tts, provider_name)
    voice = (
        chapter.voice_id
        if chapter is not None and chapter.voice_id is not None
        else provider_settings.voice
    )
    return provider_name, voice, provider_settings.speed


def chapter_voice(settings: Settings, chapter: Chapter) -> str:
    """Resolve an explicit per-chapter voice before the configured default."""
    return tts_selection(settings, chapter)[1]
