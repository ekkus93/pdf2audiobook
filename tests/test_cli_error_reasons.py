"""JSON errors carry a stable `reason` for failures a caller acts on (Tauri spec D2.b).

Each test triggers the real failure. Failures that are easy to reach from the CLI are
checked end to end through `--json`; the others are raised at their real source and then
passed through the CLI's own `fail()`, which is what every command uses.
"""

from __future__ import annotations

import fcntl
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import typer
from typer.testing import CliRunner

from pdf2audiobook import cli, review_transaction
from pdf2audiobook.cli import app
from pdf2audiobook.document.structure import render_chapter_texts
from pdf2audiobook.errors import AudiobookError, ChapterConflictError, LLMError
from pdf2audiobook.llm import OpenAICompatibleProvider
from pdf2audiobook.llm.budget import BookLLMBudgetLedger
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock
from pdf2audiobook.review_transaction import ReviewRecoveryRequired
from pdf2audiobook.review_ui import save_chapter_updates
from pdf2audiobook.workspace import write_manifest

runner = CliRunner()
SECRET = "PRIVATE_REASON_BOOK_TEXT_31"


def _error(result: Any) -> dict[str, Any]:
    payload = json.loads(result.stderr)
    assert payload["ok"] is False
    return payload["error"]


def _via_fail(exc: AudiobookError, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    """Report a real exception exactly as a command's `--json` error path does."""
    with pytest.raises(typer.Exit) as exited:
        cli.fail(exc, json_output=True)
    assert exited.value.exit_code == exc.exit_code
    return json.loads(capsys.readouterr().err)["error"]


def _manifest(**changes: Any) -> BookManifest:
    values: dict[str, Any] = {
        "schema_version": 3,
        "input_sha256": "x",
        "title": "Book",
        "source_path": "source.pdf",
        "blocks": [
            DocumentBlock(id="b0", text=f"{SECRET} one.", page_index=0),
            DocumentBlock(id="b1", text="Second chapter text.", page_index=1),
        ],
        "chapters": [
            Chapter(id="a", number=1, title="One", start_block=0, end_block=1, confidence=1),
            Chapter(id="b", number=2, title="Two", start_block=1, end_block=2, confidence=1),
        ],
    }
    values.update(changes)
    return BookManifest(**values)


def _workspace(tmp_path: Path, manifest: BookManifest) -> tuple[Path, Path]:
    folder = tmp_path / "workspace"
    folder.mkdir()
    path = folder / "manifest.json"
    write_manifest(path, manifest)
    render_chapter_texts(manifest, folder)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"synthetic")
    return source, path


def _dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manifest: BookManifest) -> Any:
    source, path = _workspace(tmp_path, manifest)
    monkeypatch.setattr("pdf2audiobook.pipeline.analyze_book", lambda *_a, **_k: path)
    return runner.invoke(app, ["convert", str(source), "--no-config", "--dry-run", "--json"])


def test_low_boundary_confidence_is_review_required(tmp_path, monkeypatch) -> None:
    chapters = [
        Chapter(id="a", number=1, title="One", start_block=0, end_block=1, confidence=0.5),
        Chapter(id="b", number=2, title="Two", start_block=1, end_block=2, confidence=1),
    ]
    result = _dry_run(tmp_path, monkeypatch, _manifest(chapters=chapters))

    assert result.exit_code == 6
    assert _error(result) == {
        "type": "AudioError",
        "code": 6,
        "message": "Chapter 1 has low boundary confidence; review the manifest before synthesis",
        "reason": "review_required",
    }
    assert SECRET not in result.stderr


def test_unapproved_empty_chapter_is_review_required(tmp_path, monkeypatch) -> None:
    blocks = [
        DocumentBlock(id="b0", text="...", page_index=0),
        DocumentBlock(id="b1", text="Second chapter text.", page_index=1),
    ]
    result = _dry_run(
        tmp_path, monkeypatch, _manifest(blocks=blocks, review_required=["empty_chapter"])
    )

    assert result.exit_code == 6
    assert _error(result) == {
        "type": "AudioError",
        "code": 6,
        "message": "Chapter 1 has no speakable text; review and approve it before synthesis",
        "reason": "review_required",
    }


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (
            "damaged_source",
            "Chapter 1 comes from a damaged source; review and approve it before synthesis",
        ),
        (
            "ambiguous_page_numbers",
            "Chapter 1 has ambiguous page-number cleanup; review and approve it",
        ),
    ],
)
def test_book_wide_review_reason_needs_acknowledgement(
    tmp_path, monkeypatch, code: str, message: str
) -> None:
    result = _dry_run(tmp_path, monkeypatch, _manifest(review_required=[code]))

    assert result.exit_code == 6
    assert _error(result) == {
        "type": "AudioError",
        "code": 6,
        "message": message,
        "reason": "review_acknowledgement_required",
    }


def test_locked_workspace_is_workspace_locked(tmp_path) -> None:
    _, path = _workspace(tmp_path, _manifest())
    with (path.parent / ".convert.lock").open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        result = runner.invoke(app, ["recover", str(path), "--json"])

    assert result.exit_code == 6
    error = _error(result)
    assert error["type"] == "WorkspaceLockedError"
    assert error["code"] == 6
    assert "already running" in error["message"]
    assert error["reason"] == "workspace_locked"


def test_pending_update_is_pending_recovery(tmp_path, monkeypatch) -> None:
    blocks = [DocumentBlock(id=f"b{i}", text=f"Body {i}.", page_index=0) for i in range(3)]
    chapters = [
        Chapter(id="a", number=1, title="One", start_block=0, end_block=1, confidence=1),
        Chapter(id="b", number=2, title="Two", start_block=1, end_block=3, confidence=1),
    ]
    manifest = _manifest(blocks=blocks, chapters=chapters)
    _, path = _workspace(tmp_path, manifest)
    original = review_transaction.atomic_write

    def fail_manifest(target: Path, data: bytes) -> None:
        if target == path:
            raise OSError("failure")
        original(target, data)

    updates = [
        {"id": "a", "title": "One", "start_block": 0, "end_block": 2},
        {"id": "b", "title": "Two", "start_block": 2, "end_block": 3},
    ]
    with monkeypatch.context() as patch:
        patch.setattr(review_transaction, "atomic_write", fail_manifest)
        with pytest.raises(ReviewRecoveryRequired):
            save_chapter_updates(path, updates)
    # A file changed after the interruption blocks automatic completion.
    (path.parent / "chapters" / "001.txt").write_text("Hand edit.", encoding="utf-8")

    result = runner.invoke(
        app, ["pack-m4b", str(path), "--output", str(tmp_path / "book.m4b"), "--json"]
    )

    assert result.exit_code == 4
    error = _error(result)
    assert error["type"] == "PendingRecoveryError"
    assert error["code"] == 4
    assert "recover" in error["message"]
    assert error["reason"] == "pending_recovery"


def test_edited_chapter_conflict_is_chapter_conflict(tmp_path, capsys) -> None:
    manifest = _manifest()
    _, path = _workspace(tmp_path, manifest)
    folder = path.parent
    (folder / "chapters" / "001.txt").write_text("Hand edit.", encoding="utf-8")
    render_chapter_texts(manifest, folder)  # the edit is observed and recorded
    moved = manifest.model_copy(deep=True)
    moved.blocks[0] = DocumentBlock(id="b0", text="Changed source text.", page_index=0)

    with pytest.raises(ChapterConflictError) as raised:
        render_chapter_texts(moved, folder)

    error = _via_fail(raised.value, capsys)
    assert error == {
        "type": "ChapterConflictError",
        "code": 4,
        "message": str(raised.value),
        "reason": "chapter_conflict",
    }


def _provider(handler: Any, **options: Any) -> OpenAICompatibleProvider:
    values: dict[str, Any] = {
        "provider": "llama-server",
        "base_url": "http://127.0.0.1:8080/v1",
        "model": "mock",
        "allow_remote": False,
        "max_retries": 0,
        "max_context_tokens": 16384,
        "transport": httpx.MockTransport(handler),
    }
    values.update(options)
    return OpenAICompatibleProvider(**values)


def _raised(provider: OpenAICompatibleProvider, text: str = "y") -> LLMError:
    with provider, pytest.raises(LLMError) as raised:
        provider.complete_json(instructions="x", document_text=text)
    return raised.value


def test_refused_connection_is_llm_unreachable(capsys) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    error = _via_fail(_raised(_provider(refuse)), capsys)

    assert error == {
        "type": "LLMError",
        "code": 5,
        "message": "llama-server LLM transport failure",
        "reason": "llm_unreachable",
    }


def test_timeout_is_not_reported_as_unreachable(capsys) -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    error = _via_fail(_raised(_provider(slow)), capsys)

    assert error["type"] == "LLMError" and "timed out" in error["message"]
    assert "reason" not in error


@pytest.mark.ollama_context
def test_unreachable_ollama_is_llm_unreachable(capsys) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    provider = _provider(refuse, provider="ollama", base_url="http://127.0.0.1:11434/v1")
    error = _via_fail(_raised(provider), capsys)

    assert error == {
        "type": "LLMError",
        "code": 5,
        "message": "Could not read the context length Ollama serves for the model",
        "reason": "llm_unreachable",
    }


def test_request_over_the_configured_context_is_llm_context_too_small(capsys) -> None:
    def never(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nothing may be sent")

    provider = _provider(never, max_context_tokens=2048, max_output_tokens=1024)
    error = _via_fail(_raised(provider, SECRET * 100), capsys)

    assert error == {
        "type": "LLMError",
        "code": 5,
        "message": "LLM request exceeds configured context and output reserve",
        "reason": "llm_context_too_small",
    }


@pytest.mark.ollama_context
def test_request_over_the_served_context_is_llm_context_too_small(capsys) -> None:
    def server(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/generate":
            return httpx.Response(200, json={"done": True})
        if request.url.path == "/api/ps":
            model = {"name": "mock:latest", "model": "mock:latest", "context_length": 4096}
            return httpx.Response(200, json={"models": [model]})
        raise AssertionError("nothing may be sent")

    provider = _provider(
        server, provider="ollama", base_url="http://127.0.0.1:11434/v1", max_output_tokens=1024
    )
    error = _via_fail(_raised(provider, "PRIVATE " * 600), capsys)

    assert error["reason"] == "llm_context_too_small"
    assert error["message"].startswith(
        "LLM request exceeds the context length the Ollama server serves"
    )


@pytest.mark.parametrize("content", ["", '{"edits":[{"original":"cut'])
def test_answer_cut_off_at_the_cap_is_llm_output_cap(capsys, content: str) -> None:
    def cut(request: httpx.Request) -> httpx.Response:
        choice = {"message": {"content": content}, "finish_reason": "length"}
        return httpx.Response(200, json={"choices": [choice]})

    error = _via_fail(_raised(_provider(cut)), capsys)

    assert error["type"] == "LLMError" and error["code"] == 5
    assert "output cap" in error["message"]
    assert error["reason"] == "llm_output_cap"


def test_used_up_request_budget_is_budget_exhausted(tmp_path, capsys) -> None:
    ledger = BookLLMBudgetLedger(tmp_path / "budget.sqlite3")
    ledger.reserve(
        request_hash="a", provider_hash="b", max_requests=1, max_tokens=None, max_usd=None
    )

    with pytest.raises(LLMError) as raised:
        ledger.reserve(
            request_hash="c", provider_hash="b", max_requests=1, max_tokens=None, max_usd=None
        )

    assert _via_fail(raised.value, capsys) == {
        "type": "LLMError",
        "code": 5,
        "message": "Per-book LLM request budget exhausted",
        "reason": "budget_exhausted",
    }


def test_error_without_a_reason_has_no_reason_key(tmp_path) -> None:
    result = runner.invoke(
        app, ["convert", str(tmp_path / "missing.pdf"), "--no-config", "--no-llm", "--json"]
    )

    assert result.exit_code == 3
    assert _error(result) == {
        "type": "InputError",
        "code": 3,
        "message": "PDF not found; check the input path and permissions",
    }
