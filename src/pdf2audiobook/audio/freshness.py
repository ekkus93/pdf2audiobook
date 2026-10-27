"""Validation of owned chapter-audio cache sidecars."""

from pathlib import Path

from pdf2audiobook.jsonio import load_bounded_json
from pdf2audiobook.workspace import digest_file


def valid_mp3_sidecar(audio_path: Path) -> dict[str, object] | None:
    """Return a verified owned sidecar; foreign or stale files are never trusted."""
    record = audio_path.with_suffix(".cache.json")
    data = load_bounded_json(record, max_bytes=4096, max_depth=8)
    if not isinstance(data, dict):
        return None
    rendering_inputs = data.get("rendering_inputs")
    footnote_policy = (
        rendering_inputs.get("footnotes") if isinstance(rendering_inputs, dict) else None
    )
    if not isinstance(footnote_policy, str) or footnote_policy not in {
        "warn",
        "inline",
        "end",
        "omit",
    }:
        return None
    try:
        valid = (
            isinstance(data.get("chapter_id"), str)
            and data.get("sidecar_version") == 3
            and isinstance(data.get("text_sha256"), str)
            and isinstance(data.get("fingerprint"), str)
            and isinstance(data.get("bytes"), int)
            and not isinstance(data.get("bytes"), bool)
            and data["bytes"] == audio_path.stat().st_size
            and isinstance(data.get("sha256"), str)
            and data["sha256"] == digest_file(audio_path)
        )
    except OSError:
        return None
    return data if valid else None
