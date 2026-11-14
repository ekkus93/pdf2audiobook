"""Errors the desktop app shows carry no book content (Tauri spec D8.c, TD9.03).

A real PDF whose title, file name and text carry marker strings goes through the commands the
app runs; every failure the app turns into an error dialog is provoked for real, and neither
the JSON error nor anything else the command prints may contain a marker. The app's own log is
covered by `desktop/src-tauri/src/privacy.rs`.
"""

from __future__ import annotations

import fcntl
import json
import socket
from pathlib import Path
from typing import Any

import fitz
import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.models import CleanupEdit
from pdf2audiobook.workspace import read_manifest, write_manifest

runner = CliRunner()
TITLE = "TITLEMARKER4471"
FILE_NAME = "FILEMARKER9083"
TEXT = "TEXTMARKER2265"
MARKERS = (TITLE, FILE_NAME, TEXT)


def _closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def book(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    config = tmp_path / "xdg"
    (config / "pdf2audiobook").mkdir(parents=True)
    # An LLM server that refuses connections, on loopback only.
    (config / "pdf2audiobook" / "config.toml").write_text(
        f'[llm.llama_server]\nbase_url = "http://127.0.0.1:{_closed_port()}/v1"\nmodel = "local"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    source = tmp_path / f"{FILE_NAME}.pdf"
    pdf = fitz.open()
    pdf.set_metadata({"title": TITLE})
    for index in range(2):
        page = pdf.new_page()
        page.insert_text((80, 60), f"Chapter {index + 1}")
        page.insert_text((80, 115), f"{TEXT} sentence {index + 1} of the book.")
    pdf.save(source)
    pdf.close()
    output = tmp_path / "out"
    analyzed = _run("analyze", str(source), "--no-llm", "--ocr", "never", "--output", str(output))
    assert analyzed.exit_code == 0, analyzed.output
    manifest = Path(json.loads(analyzed.stdout)["manifest"])
    assert read_manifest(manifest).title == TITLE, "the markers must really be in the book"
    return {"source": source, "output": output, "manifest": manifest, "tmp": tmp_path}


def _run(*args: str) -> Any:
    return runner.invoke(app, ["--no-progress", *args, "--json"])


def _failed(result: Any, *, reason: str | None = None) -> dict[str, Any]:
    """The JSON error the app shows, after checking no marker or path was printed."""
    assert result.exit_code != 0, result.output
    for marker in MARKERS:
        assert marker not in result.stderr, result.stderr
        assert marker not in result.stdout, result.stdout
    error = json.loads(result.stderr.strip().splitlines()[-1])["error"]
    if reason is not None:
        assert error.get("reason") == reason, error
    return error


def test_review_required(book: dict[str, Path]) -> None:
    manifest = read_manifest(book["manifest"])
    manifest.chapters[0].confidence = 0.1
    write_manifest(book["manifest"], manifest)
    result = _run(
        "convert", str(book["source"]), "--no-llm", "--ocr", "never",
        "--output", str(book["output"]), "--dry-run",
    )  # fmt: skip
    _failed(result, reason="review_required")


def test_workspace_locked(book: dict[str, Path]) -> None:
    # As another process would hold it (workspace_lock itself is re-entrant within a process).
    with (book["manifest"].parent / ".convert.lock").open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        result = _run("recover", str(book["manifest"]))
    _failed(result, reason="workspace_locked")


def test_llm_unreachable(book: dict[str, Path]) -> None:
    result = _run(
        "analyze", str(book["source"]), "--llm-provider", "llama-server", "--ocr", "never",
        "--output", str(book["tmp"] / "llm-out"),
    )  # fmt: skip
    _failed(result, reason="llm_unreachable")


def test_pack_m4b_without_audio(book: dict[str, Path]) -> None:
    result = _run(
        "pack-m4b", str(book["manifest"]), "--output", str(book["tmp"] / f"{FILE_NAME}.m4b")
    )
    assert "stale or missing" in _failed(result)["message"]


def test_budget_without_a_ledger(book: dict[str, Path]) -> None:
    _failed(_run("budget", "show", "--output", str(book["manifest"].parent)))


def test_unreadable_book(book: dict[str, Path]) -> None:
    broken = book["tmp"] / f"{FILE_NAME}-{TITLE}.pdf"
    broken.write_bytes(f"%PDF-1.7 {TEXT} not really a PDF".encode())
    _failed(_run("inspect", str(broken)))


def test_edits_list_without_text_carries_none(book: dict[str, Path]) -> None:
    manifest = read_manifest(book["manifest"])
    block = next(item for item in manifest.blocks if TEXT in item.text)
    manifest.edits.append(
        CleanupEdit(
            block_id=block.id,
            original=block.text,
            replacement=block.text.replace("sentence", "line"),
            reason=f"model note about {TEXT}",
            confidence=0.8,
            accepted=False,
            provider="ollama",
        )
    )
    write_manifest(book["manifest"], manifest)
    result = _run("edits", "list", str(book["manifest"]))
    assert result.exit_code == 0, result.output
    for marker in MARKERS:
        assert marker not in result.stdout
