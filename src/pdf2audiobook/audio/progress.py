"""Bounded, content-free synthesis progress persistence."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import NotRequired, TypedDict

from pdf2audiobook.errors import AudioError
from pdf2audiobook.jsonio import json_within_depth
from pdf2audiobook.logging import log_event


class _ChunkProgress(TypedDict):
    number: int
    cache_key: str
    status: str
    source_start: int
    source_end: int
    paragraph_boundary_before: bool
    text_sha256: str
    sha256: NotRequired[str | None]
    bytes: NotRequired[int | None]


class _SynthesisProgress(TypedDict):
    schema_version: int
    fingerprint: str
    total_chunks: int
    pause_count: int
    completed_chunks: int
    status: str
    chunks: list[_ChunkProgress]
    mapping: list[dict[str, int | str]]


_MAX_PROGRESS_RECORD_BYTES = 16 * 1024
_MAX_PROGRESS_FILE_BYTES = 64 * 1024 * 1024
_MAX_PROGRESS_RECORDS = 200_000


def _write_progress_record(stream, record: dict[str, object]) -> None:
    encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > _MAX_PROGRESS_RECORD_BYTES:
        raise AudioError("TTS progress record exceeds safe size limit")
    stream.write(encoded + b"\n")


def _start_progress_stream(path: Path | None, progress: _SynthesisProgress):
    if path is None:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        stream = path.open("wb")
    except OSError:
        raise AudioError("Could not write TTS progress") from None
    header = {key: value for key, value in progress.items() if key not in {"chunks", "mapping"}}
    _write_progress_record(stream, {"event": "header", **header})
    mappings = {
        row["number"]: row for row in progress["mapping"] if isinstance(row.get("number"), int)
    }
    for chunk in progress["chunks"]:
        _write_progress_record(
            stream,
            {"event": "chunk", "chunk": chunk, "mapping": mappings.get(chunk["number"])},
        )
    for row in progress["mapping"]:
        if row.get("kind") == "pause":
            _write_progress_record(stream, {"event": "mapping", "mapping": row})
    stream.flush()
    return stream


def _append_progress_update(
    stream,
    *,
    number: int,
    status: str,
    completed_chunks: int,
    sha256: str | None = None,
    byte_count: int | None = None,
) -> None:
    if stream is None:
        return
    update: dict[str, object] = {
        "event": "chunk_update",
        "number": number,
        "status": status,
        "completed_chunks": completed_chunks,
    }
    if sha256 is not None:
        update["sha256"] = sha256
    if byte_count is not None:
        update["bytes"] = byte_count
    _write_progress_record(stream, update)
    stream.flush()


def _warn_progress_unavailable() -> None:
    log_event("progress_unavailable", level=logging.WARNING, stage="chapter_audio")


def read_synthesis_progress(path: Path) -> dict[str, object] | None:
    """Reconstruct bounded JSON-lines progress records; return None if unavailable."""
    header: dict[str, object] | None = None
    chunks: dict[int, dict[str, object]] = {}
    mapping: list[dict[str, object]] = []
    total_bytes = 0
    records = 0
    try:
        with path.open("rb") as stream:
            while line := stream.readline(_MAX_PROGRESS_RECORD_BYTES + 2):
                records += 1
                total_bytes += len(line)
                if (
                    len(line) > _MAX_PROGRESS_RECORD_BYTES + 1
                    or total_bytes > _MAX_PROGRESS_FILE_BYTES
                    or records > _MAX_PROGRESS_RECORDS
                    or not line.endswith(b"\n")
                ):
                    _warn_progress_unavailable()
                    return None
                record = json.loads(line)
                if not isinstance(record, dict) or not json_within_depth(record, 8):
                    _warn_progress_unavailable()
                    return None
                event = record.get("event")
                if event == "header":
                    if header is not None:
                        _warn_progress_unavailable()
                        return None
                    header = {key: value for key, value in record.items() if key != "event"}
                elif event == "chunk":
                    chunk = record.get("chunk")
                    row = record.get("mapping")
                    if not isinstance(chunk, dict) or not isinstance(row, dict):
                        _warn_progress_unavailable()
                        return None
                    number = chunk.get("number")
                    if not isinstance(number, int) or number in chunks:
                        _warn_progress_unavailable()
                        return None
                    chunks[number] = dict(chunk)
                    mapping.append(dict(row))
                elif event == "mapping":
                    row = record.get("mapping")
                    if not isinstance(row, dict):
                        _warn_progress_unavailable()
                        return None
                    mapping.append(dict(row))
                elif event == "chunk_update":
                    number = record.get("number")
                    status = record.get("status")
                    chunk = chunks.get(number) if isinstance(number, int) else None
                    if chunk is None or status not in {"pending", "completed", "failed"}:
                        _warn_progress_unavailable()
                        return None
                    chunk["status"] = status
                    for key in ("sha256", "bytes"):
                        if key in record:
                            chunk[key] = record[key]
                    completed = record.get("completed_chunks")
                    if isinstance(completed, int):
                        if header is None:
                            _warn_progress_unavailable()
                            return None
                        header["completed_chunks"] = completed
                elif event == "status":
                    status = record.get("status")
                    if header is None or status not in {"in_progress", "completed", "failed"}:
                        _warn_progress_unavailable()
                        return None
                    header["status"] = status
                else:
                    _warn_progress_unavailable()
                    return None
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
        _warn_progress_unavailable()
        return None
    if header is None:
        _warn_progress_unavailable()
        return None
    header["chunks"] = [chunks[number] for number in sorted(chunks)]
    header["mapping"] = sorted(
        mapping,
        key=lambda item: (
            item.get("source_start") if isinstance(item.get("source_start"), int) else -1,
            item.get("source_end") if isinstance(item.get("source_end"), int) else -1,
        ),
    )
    return header
