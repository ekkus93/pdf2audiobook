"""`review --json` prints its address as one JSON line once listening (Tauri spec D2.c)."""

from __future__ import annotations

import json
import queue
import signal
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock
from pdf2audiobook.workspace import write_manifest

runner = CliRunner()


def _manifest(tmp_path: Path) -> Path:
    path = tmp_path / "manifest.json"
    write_manifest(
        path,
        BookManifest(
            schema_version=3,
            input_sha256="x",
            title="Book",
            source_path="source.pdf",
            blocks=[DocumentBlock(id="b", text="Text.", page_index=0)],
            chapters=[
                Chapter(id="c", number=1, title="One", start_block=0, end_block=1, confidence=1)
            ],
        ),
    )
    return path


class _FakeServer:
    server_address = ("127.0.0.1", 8765)

    def serve_forever(self) -> None:
        raise KeyboardInterrupt

    def server_close(self) -> None:
        pass


def test_real_server_on_port_zero_reports_a_reachable_address(tmp_path: Path) -> None:
    command = [
        sys.executable,
        "-c",
        "from pdf2audiobook.cli import app; app()",
        "review",
        str(_manifest(tmp_path)),
        "--json",
        "--port",
        "0",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    lines: queue.Queue[str] = queue.Queue()
    assert process.stdout is not None
    threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
    try:
        line = lines.get(timeout=30)
        payload = json.loads(line)
        assert set(payload) == {"url", "port"}
        assert isinstance(payload["port"], int) and payload["port"] > 0
        assert payload["url"] == f"http://127.0.0.1:{payload['port']}/"
        with urllib.request.urlopen(payload["url"], timeout=10) as response:
            assert response.status == 200
            assert b"Chapter review" in response.read()
    finally:
        process.send_signal(signal.SIGINT)
        out, _ = process.communicate(timeout=30)
    assert process.returncode == 0
    assert out == ""  # nothing after the address line


def test_json_mode_prints_only_the_address_line(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "pdf2audiobook.review_ui.create_review_server", lambda *_a, **_k: _FakeServer()
    )

    result = runner.invoke(app, ["review", str(_manifest(tmp_path)), "--json"])

    assert result.exit_code == 0, result.stderr
    assert result.stdout == '{"url": "http://127.0.0.1:8765/", "port": 8765}\n'


def test_human_mode_output_is_unchanged(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "pdf2audiobook.review_ui.create_review_server", lambda *_a, **_k: _FakeServer()
    )

    result = runner.invoke(app, ["review", str(_manifest(tmp_path))])

    assert result.exit_code == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr.splitlines() == [
        "Chapter review UI: http://127.0.0.1:8765/",
        "Press Ctrl+C to stop the local review server.",
        "Review server stopped.",
    ]
