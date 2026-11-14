"""JSON forms of model readiness and verification results (spec §3, §5; AV1.05).

Shapes are versioned and pinned by `desktop/contracts/asr-models.schema.json` and
`desktop/contracts/audio-verification.schema.json`. A report holds book text: only the
excerpts around flags, and full transcripts only when the user asked to keep them (spec §12).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pdf2audiobook.verification.compare import Token
from pdf2audiobook.verification.contracts import ChapterResult, Flag, Readiness, Word

SCHEMA_VERSION = 1
# Words of reference text kept on each side of a flag, for context.
CONTEXT_WORDS = 6


def readiness_json(readiness: Readiness) -> dict[str, Any]:
    return {
        "model": readiness.model,
        "family": readiness.family,
        "model_id": readiness.model_id,
        "revision": readiness.revision,
        "package": readiness.package,
        "package_version": readiness.package_version,
        "weights_present": readiness.weights_present,
        "size_bytes": readiness.size_bytes,
        "location": readiness.location,
        "ready": readiness.ready,
        "reason": readiness.reason,
    }


def _seconds(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def flag_json(flag: Flag, reference: Sequence[Token] = ()) -> dict[str, Any]:
    before = reference[max(0, flag.ref_start - CONTEXT_WORDS) : flag.ref_start]
    after = reference[flag.ref_end : flag.ref_end + CONTEXT_WORDS]
    return {
        "kind": flag.kind,
        "confirmed": flag.confirmed,
        "models": list(flag.models),
        "ref_start": flag.ref_start,
        "ref_end": flag.ref_end,
        "expected": flag.expected,
        "heard": dict(flag.heard),
        "before": " ".join(t.display for t in before),
        "after": " ".join(t.display for t in after),
        "start": _seconds(flag.start),
        "end": _seconds(flag.end),
        "reviewed": False,
    }


def _words_json(words: Sequence[Word]) -> list[dict[str, Any]]:
    return [{"text": w.text, "start": _seconds(w.start), "end": _seconds(w.end)} for w in words]


def chapter_json(
    result: ChapterResult, reference: Sequence[Token] = (), *, keep_transcripts: bool = False
) -> dict[str, Any]:
    chapter: dict[str, Any] = {
        "number": result.number,
        "status": result.status,
        "reason": result.reason,
        "partial": result.partial,
        "audio_sha256": result.audio_sha256,
        "reference_sha256": result.reference_sha256,
        "duration_seconds": _seconds(result.duration_seconds),
        "models": [
            {
                "model": run.model,
                "outcome": run.outcome,
                "reason": run.reason,
                "seconds": _seconds(run.seconds),
                "word_count": run.word_count,
            }
            for run in result.models
        ],
        "flags": [flag_json(flag, reference) for flag in result.flags],
    }
    if keep_transcripts:
        chapter["transcripts"] = {
            model: _words_json(words) for model, words in result.transcripts.items()
        }
    return chapter


def report_json(
    chapters: Sequence[dict[str, Any]],
    models: Sequence[Readiness],
    *,
    created_at: str,
    completed_at: str | None,
    keep_transcripts: bool,
    warnings: Sequence[str] = (),
) -> dict[str, Any]:
    """The whole run: what `verify-audio --json` prints and `reports/audio_verification.json` keeps."""
    by_status: dict[str, int] = {}
    for chapter in chapters:
        by_status[chapter["status"]] = by_status.get(chapter["status"], 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": created_at,
        "completed_at": completed_at,
        "keep_transcripts": keep_transcripts,
        "models": [
            {
                "model": r.model,
                "model_id": r.model_id,
                "revision": r.revision,
                "package_version": r.package_version,
            }
            for r in models
        ],
        "summary": {"chapters": len(chapters), "by_status": by_status},
        "chapters": list(chapters),
        "warnings": list(warnings),
    }
