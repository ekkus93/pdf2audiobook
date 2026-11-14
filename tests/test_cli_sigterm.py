"""SIGTERM stops a run the same way Ctrl+C does (Tauri spec D2.d)."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import fitz
import pytest

from pdf2audiobook.workspace import workspace_lock

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX signals only")

# The child replaces Kitten with a voice that signals the test, then blocks in synthesis.
CHILD = """
import sys, time
from pathlib import Path
import numpy as np
import pdf2audiobook.pipeline as pipeline

marker = Path(sys.argv[1])

class SlowKitten:
    sample_rate = 24000

    def __init__(self, model):
        pass

    def generate(self, text, *, voice, speed):
        marker.write_text("synthesizing")
        time.sleep(300)
        return np.zeros(2400, dtype=np.float32)

pipeline.KittenProvider = SlowKitten
from pdf2audiobook.cli import main
sys.argv = ["pdf2audiobook", *sys.argv[2:]]
main()
"""


def _book(path: Path) -> None:
    pdf = fitz.open()
    for index in range(2):
        page = pdf.new_page()
        page.insert_text((80, 60), f"Chapter {index + 1}")
        page.insert_text((80, 115), f"Test sentence from chapter {index + 1}.")
    pdf.save(path)
    pdf.close()


def _wait_for(path: Path, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while not path.exists():
        if time.monotonic() > deadline:
            raise AssertionError("synthesis never started")
        time.sleep(0.1)


def test_sigterm_during_synthesis_stops_like_ctrl_c(tmp_path: Path) -> None:
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg not installed")
    source = tmp_path / "book.pdf"
    _book(source)
    output = tmp_path / "out"
    marker = tmp_path / "started"
    command = [
        sys.executable,
        "-c",
        CHILD,
        str(marker),
        "convert",
        str(source),
        "--no-config",
        "--no-llm",
        "--ocr",
        "never",
        "--output",
        str(output),
        "--json",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        _wait_for(marker, 60)
        started = time.monotonic()
        process.send_signal(signal.SIGTERM)
        out, err = process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()

    assert process.returncode == 130
    assert time.monotonic() - started < 30
    assert out == ""
    error = json.loads(err.strip().splitlines()[-1])
    assert error == {
        "ok": False,
        "error": {"type": "Interrupted", "code": 130, "message": "Interrupted"},
        "warnings": [],
    }
    (workspace,) = output.iterdir()
    status = json.loads((workspace / "reports" / "run_status.json").read_text())
    assert status["state"] == "stopped"
    with workspace_lock(workspace):  # released: a new owner can take it at once
        pass
