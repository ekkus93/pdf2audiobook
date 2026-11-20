"""The expected narration for a chapter: exactly the text that was sent to the speech engine.

Spec §5: compare transcripts with the narration input used for synthesis, with accepted edits
and pronunciation transforms applied, not with the source re-read. The chapter text file
already has accepted edits; the chunk plan applies voice markers, citation masking and the
configured pronunciations, as conversion does. The synthesis ledger records each spoken
chunk's SHA-256, so the reference can be checked against what was actually spoken.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from pdf2audiobook.audio import audio_output_path
from pdf2audiobook.audio.freshness import valid_mp3_sidecar
from pdf2audiobook.audio.progress import read_synthesis_progress
from pdf2audiobook.audio.synthesis import _chunk_plan
from pdf2audiobook.config import Settings
from pdf2audiobook.errors import AudioError
from pdf2audiobook.models import BookManifest, Chapter
from pdf2audiobook.tts import KittenProvider, PiperProvider
from pdf2audiobook.tts.selection import tts_selection
from pdf2audiobook.workspace import digest_file, fingerprint


@dataclass(frozen=True)
class Reference:
    """The chapter's spoken text and how far it is known to match the audio."""

    text: str
    sha256: str
    audio: Path
    audio_sha256: str
    # True when every chunk's SHA-256 matches the synthesis ledger: this is what was spoken.
    exact: bool
    voice: str


@dataclass(frozen=True)
class Unavailable:
    reason: str  # one of contracts.REASONS


def _inside(path: Path, folder: Path) -> bool:
    """Whether `path` is a regular file in `folder` itself; neither may be a symlink elsewhere."""
    try:
        return (
            not folder.is_symlink()
            and path.is_file()
            and not path.is_symlink()
            and path.resolve().parent == folder.resolve()
        )
    except OSError:
        return False


def _english_piper(voice: str, settings: Settings) -> bool:
    """Piper voices are named by locale (`en_US-lessac-medium`); the model file says so too."""
    name = voice or Path(str(settings.tts.piper.model_path or "")).name
    return name.split("/")[-1].startswith("en_")


def chapter_reference(
    workspace: Path, manifest: BookManifest, chapter: Chapter, settings: Settings
) -> Reference | Unavailable:
    """The expected narration for `chapter`, or why it can't be verified."""
    provider, voice, _speed = tts_selection(settings, chapter)
    audio = audio_output_path(manifest, chapter, workspace)
    if not _inside(audio, workspace / "audio"):
        return Unavailable("audio_missing")
    sidecar = valid_mp3_sidecar(audio)
    text_file = workspace / "chapters" / f"{chapter.number:03d}.txt"
    if sidecar is None or not _inside(text_file, workspace / "chapters"):
        return Unavailable("audio_stale")
    rendering = sidecar.get("rendering_inputs")
    if isinstance(rendering, dict) and rendering.get("voice_clone") is not None:
        provider, voice = "kitten", "Cloned voice"
    elif provider == "piper" and not _english_piper(voice, settings):
        return Unavailable("unsupported_language")
    try:
        text = text_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return Unavailable("audio_stale")
    if sidecar.get("text_sha256") != hashlib.sha256(text.encode("utf-8")).hexdigest():
        return Unavailable("audio_stale")
    engine = PiperProvider if provider == "piper" else KittenProvider
    try:
        chunks, _pauses, _ranges, _voices = _chunk_plan(
            text,
            voice,
            chunk_limit=engine.max_chars_per_chunk,
            pronunciations=settings.tts.pronunciations,
            skip_citations=settings.reading.process_citations,
        )
    except AudioError:
        return Unavailable("audio_stale")
    ledger = read_synthesis_progress(
        workspace
        / ".cache"
        / "tts"
        / "progress"
        / f"{fingerprint(chapter.id, chapter.number)[:32]}.json"
    )
    spoken = [hashlib.sha256(chunk.encode("utf-8")).hexdigest() for chunk in chunks]
    chunk_records = ledger.get("chunks") if ledger is not None else None
    recorded = [
        chunk.get("text_sha256")
        for chunk in (chunk_records if isinstance(chunk_records, list) else [])
        if isinstance(chunk, dict)
    ]
    reference = " ".join(chunks)
    return Reference(
        text=reference,
        sha256=hashlib.sha256(reference.encode("utf-8")).hexdigest(),
        audio=audio,
        audio_sha256=digest_file(audio),
        exact=bool(spoken) and spoken == recorded,
        voice=voice,
    )
