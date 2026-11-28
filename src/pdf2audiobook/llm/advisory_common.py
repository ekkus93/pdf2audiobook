"""Shared LLM proposal schemas, audit records and bounded input windows."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Callable, Iterable, Iterator, Literal, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from pdf2audiobook.errors import LLMAnswerCutOff, LLMError
from pdf2audiobook.logging import log_event
from pdf2audiobook.models import DocumentBlock

LLM_PROMPT_SCHEMA_VERSION = "llm-advisory-v3"
# The start of the one line per LLM step that says how many windows got no answer.
CUT_OFF_SUMMARY = "LLM answers cut off:"
DecisionTask = Literal["heading", "contents", "cleanup", "classification", "narration", "equation"]
_Window = TypeVar("_Window", bound=tuple[Any, ...])


class HeadingProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    block_id: str
    title: str
    confidence: float = Field(ge=0, le=1)


class StructureProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headings: list[HeadingProposal] = Field(default_factory=list)


class ContentsEntryProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    block_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    page_reference: str = Field(pattern=r"^\d{1,4}$")
    confidence: float = Field(ge=0, le=1)


class BoundaryProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    block_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    confidence: float = Field(ge=0, le=1)


class ContentsBoundaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[ContentsEntryProposal] = Field(default_factory=list, max_length=60)
    boundaries: list[BoundaryProposal] = Field(default_factory=list, max_length=60)


class CleanupSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    block_id: str
    original: str
    replacement: str
    reason: str
    confidence: float = Field(ge=0, le=1)


class CleanupSuggestions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edits: list[CleanupSuggestion] = Field(default_factory=list)


class LLMDecision(BaseModel):
    """Privacy-preserving audit of one task's verifier decision on an LLM proposal."""

    model_config = ConfigDict(extra="forbid")
    task: DecisionTask
    block_id: str
    proposal_summary: str = Field(max_length=80)
    status: Literal["accepted", "rejected"]
    reason_code: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    source_sha256: str | None = None
    provider: str = "llm"
    requires_manual_review: bool = True


# Retain the old symbol for callers that imported the cleanup-only record.
CleanupDecision = LLMDecision


@runtime_checkable
class LLMProvider(Protocol):
    def list_models(self) -> list[str]:
        """Return discoverable model IDs, or raise a sanitized error."""

    def health(self) -> bool:
        """Perform a bounded remote capability/availability probe."""

    def complete_json(self, *, instructions: str, document_text: str) -> dict[str, Any]:
        """Return parsed JSON from the provider, or raise a sanitized LLMError."""


class WindowAnswers:
    """One LLM step's requests, one per window, where a window's failure stays its own.

    `plan` walks the step's windows: an oversized one is skipped, and once the last window is
    done, `finish` runs. `ask_window` asks about one window: an answer cut off at the output
    cap part way through is that window's failure alone, so the step carries on without its
    proposals. Both record why (a warning, and a rejected decision for `task`). When no window
    got an answer and at least one was cut off, the cap is too small for the step, and
    `finish` raises the error. `ask` is the same request without recording, for callers that
    record their own way. When any window was cut off, `finish` also adds one summary line
    starting with `CUT_OFF_SUMMARY` (counts only) and logs `llm_answers_cut_off`, so the result
    says how much of the step got no answer.
    """

    def __init__(
        self,
        provider: Any,
        task: DecisionTask | tuple[DecisionTask, ...] | None = None,
        label: str = "",
        warnings: list[str] | None = None,
        decisions: list[LLMDecision] | None = None,
        unit: str = "windows",
    ) -> None:
        self.provider = provider
        self.unit = unit
        # One step, or several sharing each request (cleanup and narration).
        self.tasks: tuple[DecisionTask, ...] = (
            () if task is None else task if isinstance(task, tuple) else (task,)
        )
        self.label = label
        self.warnings = warnings
        self.decisions = decisions
        self.answered = 0
        self.cut_off = 0

    def plan(self, stage: str, windows: Iterable[_Window]) -> Iterator[_Window]:
        for start, window, snippet in planned_windows(self.provider, stage, windows):
            if not window:
                warning = f"LLM {self.label} skipped oversized block at index {start}"
                self._reject(start, "oversized_source_block", warning)
                continue
            yield start, window, snippet  # type: ignore[misc]
        self.finish()

    def ask(
        self, *, instructions: str, document_text: str, image_data: bytes | None = None
    ) -> dict[str, Any] | None:
        """The answer, or None when it was cut off at the output cap."""
        try:
            if image_data is None:
                raw = self.provider.complete_json(
                    instructions=instructions, document_text=document_text
                )
            else:
                raw = self.provider.complete_json_with_image(
                    instructions=instructions, document_text=document_text, image_data=image_data
                )
        except LLMAnswerCutOff:
            self.cut_off += 1
            return None
        self.answered += 1
        return raw

    def ask_window(
        self, start: int, instructions: str, document_text: str
    ) -> dict[str, Any] | None:
        """One window's answer, or None (recorded) when it was cut off at the output cap."""
        raw = self.ask(instructions=instructions, document_text=document_text)
        if raw is None:
            warning = f"LLM {self.label} answer cut off at the output cap at block window {start}"
            self._reject(start, "answer_cut_off", warning)
        return raw

    def finish(self) -> None:
        if self.cut_off and not self.answered:
            raise LLMAnswerCutOff()
        if self.cut_off:
            asked = self.cut_off + self.answered
            if self.warnings is not None:
                self.warnings.append(
                    f"{CUT_OFF_SUMMARY} {self.label} got no answer for {self.cut_off} of {asked} "
                    f"{self.unit}; raise llm.max_output_tokens to include them"
                )
            log_event(
                "llm_answers_cut_off",
                level=logging.WARNING,
                stage="_".join(self.tasks) or "llm",
                count=self.cut_off,
            )

    def _reject(self, start: int, reason_code: str, warning: str) -> None:
        if self.warnings is not None:
            self.warnings.append(warning)
        for task in self.tasks:
            _record_decision(
                self.decisions,
                task=task,
                block_id=f"window:{start}",
                status="rejected",
                reason_code=reason_code,
            )


def _bounded_block_windows(
    blocks: list[DocumentBlock],
    *,
    window_size: int,
    max_json_bytes: int,
    record: Callable[[DocumentBlock], dict[str, Any]],
) -> Iterator[tuple[int, list[DocumentBlock], str]]:
    """Bound all serialized source records and add read-only lookback when feasible.

    The primary block list never contains lookback context. Callers validate
    suggestions against that primary list, so prior records cannot be edited.
    """
    if window_size < 1 or max_json_bytes < 2:
        raise LLMError("LLM window_size and chunk_tokens must be positive")
    window: list[DocumentBlock] = []
    encoded: list[str] = []
    size = 2
    start = 0
    preceding: DocumentBlock | None = None

    def payload() -> str:
        parts = list(encoded)
        if preceding is not None:
            context = json.dumps(
                {**record(preceding), "context_only": True},
                ensure_ascii=True,
                separators=(",", ":"),
            )
            if len(context) + 1 + size <= max_json_bytes:
                parts.insert(0, context)
        return "[" + ",".join(parts) + "]"

    for index, block in enumerate(blocks):
        entry = json.dumps(record(block), ensure_ascii=True, separators=(",", ":"))
        entry_size = len(entry)
        if entry_size + 2 > max_json_bytes:
            if window:
                yield start, window, payload()
                window, encoded, size = [], [], 2
            # An omitted oversized source record breaks contextual adjacency.
            preceding = None
            yield index, [], ""
            continue
        if window and (len(window) >= window_size or size + 1 + entry_size > max_json_bytes):
            yield start, window, payload()
            preceding = window[-1]
            window, encoded, size = [], [], 2
        if not window:
            start = index
        window.append(block)
        encoded.append(entry)
        size += entry_size + (1 if len(window) > 1 else 0)
    if window:
        yield start, window, payload()


def _diagnostic_block_id(candidate: str, known_ids: set[str]) -> str:
    """Never echo arbitrary model-generated identifiers into local diagnostics.

    Existing canonical IDs may help trace a rejected context-only candidate,
    but values that are unknown or contain non-identifier text are untrusted.
    """
    if (
        candidate in known_ids
        and len(candidate) <= 80
        and candidate.isascii()
        and all(char.isalnum() or char in "-_:." for char in candidate)
    ):
        return candidate
    return "<unrecognized>"


def _record_decision(
    records: list[LLMDecision] | None,
    *,
    task: DecisionTask,
    block_id: str,
    status: Literal["accepted", "rejected"],
    reason_code: str,
    confidence: float | None = None,
    source: DocumentBlock | None = None,
) -> None:
    if records is not None:
        safe_block_id = (
            block_id
            if block_id == "<unrecognized>"
            or (
                len(block_id) <= 80
                and block_id.isascii()
                and all(char.isalnum() or char in "-_:." for char in block_id)
            )
            else "<unrecognized>"
        )
        records.append(
            LLMDecision(
                task=task,
                block_id=safe_block_id,
                proposal_summary=(
                    "no proposal in task window"
                    if reason_code == "no_proposals"
                    else f"{task} proposal"
                ),
                status=status,
                reason_code=reason_code,
                confidence=confidence,
                source_sha256=hashlib.sha256(source.text.encode("utf-8")).hexdigest()
                if source is not None
                else None,
            )
        )


# Glyph shapes OCR engines confuse. Anything else (word choice, tense, quote
# style, punctuation, completing a hyphenated word from the next line) is an
# edit to the author's text, not a transcription fix.
_OCR_CONFUSIONS = {
    frozenset(pair)
    for pair in (
        ("0", "O"), ("0", "o"), ("1", "l"), ("1", "I"), ("l", "I"), ("|", "l"),
        ("|", "I"), ("i", "l"), ("i", "j"), ("5", "S"), ("5", "s"), ("8", "B"),
        ("6", "b"), ("9", "g"), ("2", "Z"), ("h", "b"), ("c", "e"), ("n", "u"),
        ("f", "t"), ("ſ", "s"), ("ſ", "f"), ("f", "s"), ("rn", "m"), ("in", "m"),
        ("ni", "m"), ("cl", "d"), ("li", "h"), ("ri", "n"), ("ii", "u"), ("ii", "n"),
        ("vv", "w"), ("ﬁ", "fi"), ("ﬂ", "fl"), ("ﬀ", "ff"), ("ﬃ", "ffi"), ("ﬄ", "ffl"),
        ("c", "C"), ("o", "O"), ("s", "S"), ("v", "V"), ("w", "W"), ("x", "X"),
        ("z", "Z"),
    )
}  # fmt: skip
_OCR_CONFUSION_PAIRS = [(a, b) for pair in _OCR_CONFUSIONS for a in pair for b in pair if a != b]


def _ocr_plausible(original: str, replacement: str) -> bool:
    """Whether ``replacement`` differs from ``original`` only by OCR misreads.

    Aligns the two lines allowing identical characters, known glyph
    confusions and added or removed whitespace (split or joined words).
    """
    n, m = len(original), len(replacement)
    reachable: list[set[int]] = [set() for _ in range(n + 1)]
    reachable[0].add(0)
    for i in range(n + 1):
        pending = list(reachable[i])
        while pending:
            j = pending.pop()
            if j < m and replacement[j].isspace() and j + 1 not in reachable[i]:
                reachable[i].add(j + 1)
                pending.append(j + 1)
        if i == n:
            break
        for j in reachable[i]:
            if original[i].isspace():
                reachable[i + 1].add(j)
            if j < m and original[i] == replacement[j]:
                reachable[i + 1].add(j + 1)
            for a, b in _OCR_CONFUSION_PAIRS:
                if original.startswith(a, i) and replacement.startswith(b, j):
                    reachable[i + len(a)].add(j + len(b))
    return m in reachable[n]


def planned_windows(provider: Any, stage: str, windows: Iterable[_Window]) -> list[_Window]:
    """Materialize bounded windows and announce the request count for progress display."""
    planned = list(windows)
    announce = getattr(provider, "expect_requests", None)
    if callable(announce):
        announce(sum(1 for _start, window, _snippet in planned if window), stage)
    return planned
