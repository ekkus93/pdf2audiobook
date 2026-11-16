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


def without_transcripts(chapter: dict[str, Any]) -> dict[str, Any]:
    """A chapter with its full transcripts removed; excerpts and vote metadata stay (AVF2)."""
    return {key: value for key, value in chapter.items() if key != "transcripts"}


def retains_transcripts(chapters: Sequence[dict[str, Any]]) -> bool:
    """Whether any chapter of a report carries full transcripts: the report's retention field."""
    return any("transcripts" in chapter for chapter in chapters)


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


_STATUS_TEXT = {
    "no_mismatch_detected": "no mismatch detected",
    "possible_mismatch": "possible mismatch",
    "model_disagreement": "models disagree",
    "verification_unavailable": "not verified",
}


def _clock(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes}:{rest:02d}"


_REASON_TEXT = {
    "audio_missing": "no audio to check; convert the chapter first",
    "audio_stale": "the audio no longer matches its chapter text; convert the chapter again",
    "narration_not_spoken": (
        "the chapter text or pronunciations changed since it was spoken, so it wasn't compared; "
        "speak the chapter again first"
    ),
    "audio_undecodable": "FFmpeg couldn't read this chapter's MP3; check that FFmpeg is installed",
    "cancelled": "the check was stopped",
}
_WARNING_TEXT = {
    "ffmpeg_missing": "FFmpeg was not found, so no chapter could be checked; install FFmpeg",
    "whisper_low_memory": "Whisper on this CPU needs about 8 GB of RAM; it may be slow or fail",
}


def report_text(
    report: dict[str, Any], *, numbers: set[int] | None = None, details: bool = False
) -> str:
    """`verify-audio` for people. Book text (expected and heard words) only with `details`."""
    lines = []
    for chapter in report["chapters"]:
        if numbers is not None and chapter["number"] not in numbers:
            continue
        voted = [m["model"] for m in chapter["models"] if m["outcome"] == "ok"]
        text = f"Chapter {chapter['number']}: {_STATUS_TEXT[chapter['status']]}"
        if chapter["reason"]:
            text += f" ({_REASON_TEXT.get(chapter['reason'], chapter['reason'].replace('_', ' '))})"
        elif chapter["partial"]:
            text += f" (partial: {len(voted)} of 3 models)"
        lines.append(text)
        for flag in chapter["flags"]:
            if not flag["confirmed"] and not details:
                continue
            where = f"{_clock(flag['start'])}-{_clock(flag['end'])}"
            agreed = ", ".join(flag["models"])
            line = f"  {where} {flag['kind']} heard by {agreed}"
            if not flag["confirmed"]:
                line += " only"
            if details:
                line += f": expected {flag['expected']!r}, heard " + "; ".join(
                    f"{model} {heard!r}" for model, heard in flag["heard"].items()
                )
            lines.append(line)
    for code in report.get("warnings", []):
        lines.append(_WARNING_TEXT.get(code, code.replace("_", " ")))
    lines.append(
        "A flag means listen there; speech recognition is evidence, not proof. "
        "Report: reports/audio_verification.json"
    )
    return "\n".join(lines)
