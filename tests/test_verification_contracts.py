"""Typed contracts and versioned JSON schemas for audio verification (AV1.01, AV1.05)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, get_args

import jsonschema

from pdf2audiobook.verification import contracts
from pdf2audiobook.verification.compare import differences, tokenize, tokenize_text, vote
from pdf2audiobook.verification.contracts import (
    AsrBackend,
    ChapterResult,
    ModelRun,
    Readiness,
    Transcript,
    Word,
)
from pdf2audiobook.verification.report import chapter_json, readiness_json, report_json

CONTRACTS = Path(__file__).resolve().parents[1] / "desktop" / "contracts"


def _check(schema: str, payload: Any) -> None:
    contract = json.loads((CONTRACTS / f"{schema}.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(contract)
    jsonschema.Draft202012Validator(contract).validate(payload)


class _FakeBackend:
    name = "vosk"

    def readiness(self) -> Readiness:
        return Readiness(
            "vosk", "Kaldi", "vosk-model-en-us-0.22-lgraph", "x", "vosk", "0.3.45", True, 1, "/m"
        )

    def transcribe(self, wav: Path, *, should_stop: Callable[[], bool]) -> Transcript:
        return Transcript("vosk", (Word("hello", 0.0, 0.4),))


def _readiness(**changes: Any) -> Readiness:
    values: dict[str, Any] = {
        "model": "whisper",
        "family": "OpenAI Whisper",
        "model_id": "medium.en",
        "revision": "d7440d1dc186f76616474e0ff0b3b6b879abc9d1a4926b7adfa41db2d497ab4f",
        "package": "openai-whisper",
        "package_version": "20250625",
        "weights_present": True,
        "size_bytes": 1_528_006_491,
        "location": "/home/me/.cache/pdf2audiobook/asr/whisper",
    }
    values.update(changes)
    return Readiness(**values)


def test_a_backend_meets_the_interface() -> None:
    assert isinstance(_FakeBackend(), AsrBackend)
    assert not isinstance(object(), AsrBackend)


def test_readiness_needs_the_package_and_the_weights() -> None:
    assert _readiness().ready
    assert not _readiness(package_version=None, reason="model_not_installed").ready
    assert not _readiness(weights_present=False, reason="model_not_downloaded").ready


def test_readiness_json_follows_the_contract() -> None:
    payload = {
        "models": [
            readiness_json(_readiness()),
            readiness_json(
                _readiness(model="vosk", package_version=None, reason="model_not_installed")
            ),
        ],
        "directory": "/home/me/.cache/pdf2audiobook/asr",
        "warnings": [],
    }
    _check("asr-models", payload)
    assert payload["models"][1]["ready"] is False


REFERENCE = "the keeper climbed the ninety two steps and trimmed the wick of the great lamp"
INSERTED = "the keeper climbed the ninety two steps and the old bell rang and trimmed the wick of the great lamp"


def _result(keep: bool = False) -> tuple[dict[str, Any], ChapterResult]:
    reference = tokenize_text(REFERENCE)
    words = [Word(w, i * 0.5, i * 0.5 + 0.4) for i, w in enumerate(INSERTED.split())]
    found = {m: differences(m, reference, tokenize(words)) for m in ("whisper", "vosk")}
    flags = vote(reference, found)
    result = ChapterResult(
        number=3,
        status="possible_mismatch",
        reason=None,
        models=(
            ModelRun("whisper", "ok", None, 1.5, 19),
            ModelRun("wav2vec2", "failed", "model_failed"),
            ModelRun("vosk", "ok", None, 0.7, 19),
        ),
        flags=tuple(flags),
        partial=True,
        audio_sha256="a" * 64,
        reference_sha256="b" * 64,
        duration_seconds=9.5,
        transcripts={"whisper": tuple(words)},
    )
    return chapter_json(result, reference, keep_transcripts=keep), result


def test_a_report_follows_the_contract_and_keeps_only_excerpts() -> None:
    chapter, _ = _result()
    report = report_json(
        [chapter],
        [_readiness()],
        created_at="2026-11-14T12:00:00+00:00",
        completed_at="2026-11-14T12:01:00+00:00",
        keep_transcripts=False,
    )
    _check("audio-verification", report)
    assert "transcripts" not in chapter
    flag = chapter["flags"][0]
    assert flag["confirmed"] and flag["kind"] == "insertion"
    # The phrase has an "and" at each end; either may be the inserted one.
    assert flag["heard"]["whisper"] in {"the old bell rang and", "and the old bell rang"}
    assert "steps" in flag["before"].split()[-2:]
    assert flag["after"].split()[0] in {"and", "trimmed"}
    # From the inserted "and" (word 7, 3.5 s) to "rang" or the second "and" (ends by 6.4 s).
    assert 3.5 <= flag["start"] <= flag["end"] <= 6.4
    assert report["summary"] == {"chapters": 1, "by_status": {"possible_mismatch": 1}}


def test_full_transcripts_only_when_kept() -> None:
    chapter, _ = _result(keep=True)
    _check(
        "audio-verification",
        report_json([chapter], [], created_at="t", completed_at=None, keep_transcripts=True),
    )
    assert len(chapter["transcripts"]["whisper"]) == len(INSERTED.split())


def test_the_schemas_list_every_status_reason_and_model() -> None:
    report = json.loads((CONTRACTS / "audio-verification.schema.json").read_text(encoding="utf-8"))
    chapter = report["properties"]["chapters"]["items"]["properties"]
    assert set(chapter["status"]["enum"]) == set(get_args(contracts.ChapterStatus))
    assert set(chapter["reason"]["enum"]) == {*contracts.REASONS, None}
    assert set(chapter["flags"]["items"]["properties"]["kind"]["enum"]) == set(
        get_args(contracts.DifferenceKind)
    )
    models = json.loads((CONTRACTS / "asr-models.schema.json").read_text(encoding="utf-8"))
    assert models["properties"]["models"]["items"]["properties"]["model"]["enum"] == list(
        contracts.MODEL_NAMES
    )
