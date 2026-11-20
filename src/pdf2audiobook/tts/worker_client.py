"""Cancelable private-pipe protocol for local ML inference; no narration in argv."""

from __future__ import annotations

import contextlib
import json
import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from pdf2audiobook.errors import AudioError

WORKER_TIMEOUT = 300.0
STOP_GRACE = 2.0
MAX_REPLY = 128 * 1024


class WorkerClient:
    def __init__(self, command: list[str] | None = None) -> None:
        self.process = subprocess.Popen(
            command or [sys.executable, "-m", "pdf2audiobook.tts.clone_worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env={**os.environ, "PDF2AUDIOBOOK_VOICE_PARENT": str(os.getpid())},
        )

    def request(
        self, payload: dict[str, Any], *, timeout: float = WORKER_TIMEOUT
    ) -> dict[str, Any]:
        process = self.process
        assert process.stdin is not None and process.stdout is not None
        try:
            deadline, data = time.monotonic() + timeout, bytearray()
            _send(process, payload, deadline)
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while b"\n" not in data:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(min(remaining, 0.5)):
                        if remaining <= 0:
                            raise TimeoutError
                        continue
                    block = os.read(process.stdout.fileno(), 4096)
                    if not block:
                        raise ValueError("closed")
                    data.extend(block)
                    if len(data) > MAX_REPLY:
                        raise ValueError("oversized")
            response = json.loads(data)
            if not isinstance(response, dict) or response.get("ok") is not True:
                if (
                    isinstance(response, dict)
                    and response.get("reason") == "voice_reference_invalid"
                ):
                    raise AudioError(
                        "Could not condition the reference voice; check the recording and transcript",
                        error_reason="voice_reference_invalid",
                    )
                raise ValueError("backend")
            return response
        except (OSError, ValueError, TimeoutError):
            self.close()
            raise AudioError(
                "Local voice preparation or synthesis failed; check model setup and resources",
                error_reason="voice_clone_unavailable",
            ) from None
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        process = self.process
        if process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=STOP_GRACE)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        if process.stdin is not None:
            process.stdin.close()
        if process.stdout is not None:
            process.stdout.close()
        from pdf2audiobook.tts.private import cleanup_private_jobs

        # A killed ASR worker cannot run its temporary-directory context cleanup.
        # Locks preserve this run's reference and every other still-active job.
        cleanup_private_jobs()


def _send(process: subprocess.Popen[bytes], payload: dict[str, Any], deadline: float) -> None:
    """Include a blocked stdin pipe in the request deadline, even for a 64-KiB transcript."""
    assert process.stdin is not None
    fd = process.stdin.fileno()
    os.set_blocking(fd, False)
    data = memoryview((json.dumps(payload, ensure_ascii=False) + "\n").encode())
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdin, selectors.EVENT_WRITE)
        while data:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            if not selector.select(min(remaining, 0.5)):
                continue
            try:
                data = data[os.write(fd, data) :]
            except BlockingIOError:
                continue


def transcribe_reference(path: Path) -> tuple[str, dict[str, Any]]:
    from pdf2audiobook.verification.models import readiness

    state = readiness("whisper")
    if not state.ready:
        raise AudioError(
            "Provide --reference-text-file or install asr-whisper and run "
            "'pdf2audiobook asr fetch whisper'; nothing was downloaded",
            error_reason="voice_clone_unavailable",
        )
    client = WorkerClient()
    try:
        result = client.request({"command": "transcribe", "reference": str(path)})
        text = result.get("transcript")
        if not isinstance(text, str):
            raise AudioError(
                "Could not transcribe the reference", error_reason="voice_reference_invalid"
            )
        return text, {"model": state.revision, "package": state.package_version}
    finally:
        client.close()
