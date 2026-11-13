"""Audio chunk generation, caching, and single-encode chapter MP3 assembly."""

from __future__ import annotations

import re
import shutil as shutil
import subprocess as subprocess
import tempfile as tempfile
from pathlib import Path

from pdf2audiobook.audio.citations import mask_citations as mask_citations
from pdf2audiobook.audio.encoding import (
    AudioEncoder as AudioEncoder,
)
from pdf2audiobook.audio.encoding import (
    _ffmetadata_value as _ffmetadata_value,
)
from pdf2audiobook.audio.encoding import (
    _safe_chapter_workspace as _safe_chapter_workspace,
)
from pdf2audiobook.audio.encoding import (
    _validate_chapter_wav as _validate_chapter_wav,
)
from pdf2audiobook.audio.encoding import (
    _write_chapter_wav as _write_chapter_wav,
)
from pdf2audiobook.audio.encoding import (
    encode_m4b as encode_m4b,
)
from pdf2audiobook.audio.encoding import (
    encode_mp3 as encode_mp3,
)
from pdf2audiobook.audio.progress import (
    _MAX_PROGRESS_RECORD_BYTES as _MAX_PROGRESS_RECORD_BYTES,
)
from pdf2audiobook.audio.progress import (
    read_synthesis_progress as read_synthesis_progress,
)
from pdf2audiobook.audio.speech_text import (
    chunk_source_ranges as chunk_source_ranges,
)
from pdf2audiobook.audio.speech_text import (
    has_speakable_chapter_narration as has_speakable_chapter_narration,
)
from pdf2audiobook.audio.speech_text import (
    has_speakable_narration as has_speakable_narration,
)
from pdf2audiobook.audio.speech_text import (
    split_sentences as split_sentences,
)
from pdf2audiobook.audio.speech_text import (
    unspeakable_pause_ranges as unspeakable_pause_ranges,
)
from pdf2audiobook.audio.speech_text import (
    voice_marker_ids as voice_marker_ids,
)
from pdf2audiobook.audio.synthesis import (
    read_wav as read_wav,
)
from pdf2audiobook.audio.synthesis import (
    synthesize_chunks as synthesize_chunks,
)
from pdf2audiobook.audio.synthesis import (
    wav_bytes as wav_bytes,
)
from pdf2audiobook.errors import ConfigError
from pdf2audiobook.models import BookManifest, Chapter
from pdf2audiobook.narration import (
    normalize_narration_text as normalize_narration_text,
)

_MAX_COVER_BYTES = 5 * 1024 * 1024


def read_cover_image(path: str | Path | None) -> tuple[bytes, str] | None:
    """Read a bounded JPEG/PNG cover using signatures, with content-free errors."""
    if path is None:
        return None
    try:
        with Path(path).expanduser().open("rb") as source:
            data = source.read(_MAX_COVER_BYTES + 1)
    except OSError:
        raise ConfigError("Cover image is unavailable; check the configured image file") from None
    if len(data) > _MAX_COVER_BYTES:
        raise ConfigError("Cover image exceeds the 5 MiB limit")
    if data.startswith(b"\xff\xd8\xff"):
        return data, "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return data, "image/png"
    raise ConfigError("Cover image must be a JPEG or PNG file")


def safe_name(text: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9 _.-]", "_", text)
    return name.strip(" ._")[:90] or "Chapter"


def audio_output_path(manifest: BookManifest, chapter: Chapter, workspace: Path) -> Path:
    return workspace / "audio" / f"{chapter.number:03d} - {safe_name(chapter.title)}.mp3"
