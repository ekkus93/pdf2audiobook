"""Live status file, heartbeat, per-request events and slow-request warnings (R11 follow-up)."""

import io
import json
import logging
import time
from pathlib import Path
from typing import Any

import fitz
import httpx
import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.config import Settings
from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm import OpenAICompatibleProvider
from pdf2audiobook.llm.cache import CachedLLMProvider
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.progress_display import NullReporter, StatusReporter, use_reporter

PRIVATE = "Zanzibar"


def _status(folder: Path) -> dict[str, Any]:
    return json.loads((folder / "reports" / "run_status.json").read_text(encoding="utf-8"))


def test_status_file_tracks_stage_counts_and_estimate(tmp_path: Path) -> None:
    reporter = StatusReporter(NullReporter(), command="convert")
    reporter.bind_workspace(tmp_path)
    assert _status(tmp_path)["state"] == "running"
    handle = reporter.stage("Synthesizing speech", 100, "char", initial=20)
    handle.set_detail("chapter 2/5")
    handle.advance(10)
    time.sleep(0.05)
    payload = reporter._payload()
    stage = payload["stage"]
    assert stage["name"] == "Synthesizing speech" and stage["detail"] == "chapter 2/5"
    assert stage["done"] == 30 and stage["total"] == 100 and stage["unit"] == "char"
    assert stage["estimated_remaining_seconds"] is not None
    handle.close()
    after = _status(tmp_path)
    assert after["stage"] is None
    assert [item["name"] for item in after["completed_stages"]] == ["Synthesizing speech"]
    reporter.summary("done")
    reporter.close()
    assert _status(tmp_path)["state"] == "completed"


def test_cached_work_does_not_make_the_estimate_optimistic(tmp_path: Path) -> None:
    reporter = StatusReporter(NullReporter(), command="analyze")
    reporter.bind_workspace(tmp_path)
    handle = reporter.stage("Analyzing", 100, "request")
    handle.advance(50, cached=True)
    assert reporter._payload()["stage"]["estimated_remaining_seconds"] is None
    reporter.close()


def test_closing_without_a_summary_records_a_stopped_run(tmp_path: Path) -> None:
    reporter = StatusReporter(NullReporter(), command="convert")
    reporter.bind_workspace(tmp_path)
    reporter.stage("Extracting pages", 3, "page")
    reporter.close()
    status = _status(tmp_path)
    assert status["state"] == "stopped" and status["stage"] is None


def test_status_contains_only_names_counts_and_times(tmp_path: Path) -> None:
    reporter = StatusReporter(NullReporter(), command="convert")
    reporter.bind_workspace(tmp_path)
    reporter.stage("Synthesizing speech", 10, "char").advance(4)
    reporter.close()
    text = (tmp_path / "reports" / "run_status.json").read_text(encoding="utf-8")
    assert PRIVATE not in text and str(tmp_path) not in text


def test_heartbeat_prints_content_free_lines_only_when_enabled(tmp_path: Path) -> None:
    stream = io.StringIO()
    reporter = StatusReporter(
        NullReporter(), command="convert", heartbeat_seconds=0.05, stream=stream
    )
    reporter.bind_workspace(tmp_path)
    handle = reporter.stage("Analyzing with the LLM", 40, "request")
    handle.set_detail("cleanup")
    handle.advance(7)
    time.sleep(0.4)
    reporter.close()
    lines = [line for line in stream.getvalue().splitlines() if line]
    assert lines and "Analyzing with the LLM, cleanup: 7/40 request" in lines[0]
    assert "elapsed" in lines[0] and PRIVATE not in stream.getvalue()

    quiet = io.StringIO()
    silent = StatusReporter(NullReporter(), command="convert", stream=quiet, tick_seconds=0.05)
    silent.bind_workspace(tmp_path / "other")
    silent.stage("Stage", 2, "unit")
    time.sleep(0.2)
    silent.close()
    assert quiet.getvalue() == ""


def test_the_status_file_stays_fresh_while_the_main_thread_is_busy(tmp_path: Path) -> None:
    reporter = StatusReporter(NullReporter(), command="convert", tick_seconds=0.05)
    reporter.bind_workspace(tmp_path)
    reporter.stage("Analyzing with the LLM", None, "request")
    first = _status(tmp_path)["elapsed_seconds"]
    time.sleep(1.3)
    assert _status(tmp_path)["elapsed_seconds"] > first
    reporter.close()


def _pdf(tmp_path: Path) -> Path:
    source = tmp_path / "book.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Chapter 1", fontsize=24)
    page.insert_text((72, 120), f"Spoken {PRIVATE} words.", fontsize=11)
    doc.save(source)
    doc.close()
    return source


def test_json_analyze_writes_a_completed_status_and_keeps_stderr_empty(tmp_path: Path) -> None:
    source = _pdf(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "analyze",
            str(source),
            "--no-config",
            "--no-llm",
            "--ocr",
            "never",
            "--output",
            str(tmp_path / "out"),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert result.stderr == ""
    folder = Path(json.loads(result.stdout)["manifest"]).parent
    status = _status(folder)
    assert status["state"] == "completed" and status["command"] == "analyze"
    assert "Extracting pages" in [item["name"] for item in status["completed_stages"]]
    text = (folder / "reports" / "run_status.json").read_text(encoding="utf-8")
    assert PRIVATE not in text


def test_heartbeat_setting_flag_and_validation(tmp_path: Path) -> None:
    shown = CliRunner().invoke(
        app,
        ["config", "show", "--json", "--no-config"],
        env={"PDF2AUDIOBOOK_HEARTBEAT_SECONDS": "45"},
    )
    assert json.loads(shown.stdout)["general"]["heartbeat_seconds"] == 45
    assert Settings().general.heartbeat_seconds == 0
    bad = CliRunner().invoke(app, ["--heartbeat", "-1", "config", "show", "--no-config"])
    assert bad.exit_code == 2


def test_pipeline_uses_the_installed_reporter_without_an_argument(tmp_path: Path) -> None:
    events: list[tuple[Any, ...]] = []

    class Handle:
        def advance(self, count: int = 1, *, cached: bool = False) -> None: ...
        def set_total(self, total: int) -> None: ...
        def set_detail(self, text: str) -> None: ...
        def close(self) -> None: ...

    class Recorder:
        enabled = True

        def stage(self, name: str, total: int | None, unit: str, initial: int = 0) -> Handle:
            events.append((name, total, unit))
            return Handle()

        def summary(self, text: str) -> None: ...
        def close(self) -> None: ...

    source = _pdf(tmp_path)
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.llm.enabled = False
    settings.pdf.ocr = "never"
    with use_reporter(Recorder()):
        analyze_book(source, settings)
    assert ("Extracting pages", 1, "page") in events


class _Inner:
    def __init__(self) -> None:
        self.last_usage: dict[str, int] = {}
        self.fail: Exception | None = None

    def complete_json(self, *, instructions: str, document_text: str) -> dict[str, Any]:
        if self.fail is not None:
            raise self.fail
        self.last_usage = {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}
        return {"headings": []}


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int, dict[str, Any]]]:
    seen: list[tuple[str, int, dict[str, Any]]] = []
    monkeypatch.setattr(
        "pdf2audiobook.llm.cache.log_event",
        lambda event, *, level=logging.INFO, **fields: seen.append((event, level, fields)),
    )
    return seen


def _worker(tmp_path: Path, inner: _Inner) -> CachedLLMProvider:
    return CachedLLMProvider(inner, cache_dir=tmp_path / "cache", identity="x")


def test_each_request_is_logged_with_stage_time_and_tokens_but_no_content(
    tmp_path: Path, events: list
) -> None:
    worker = _worker(tmp_path, _Inner())
    worker.progress = StatusReporter(NullReporter(), command="analyze").stage("A", None, "request")
    worker.expect_requests(1, "cleanup")
    worker.complete_json(instructions="ins", document_text=f"{PRIVATE} text")
    ((event, level, fields),) = events
    assert event == "llm_request" and level == logging.DEBUG
    assert fields["stage"] == "cleanup" and fields["prompt_tokens"] == 120
    assert fields["completion_tokens"] == 30 and isinstance(fields["seconds"], float)
    assert PRIVATE not in json.dumps(fields)


def test_a_failed_request_is_logged_with_its_reason(tmp_path: Path, events: list) -> None:
    inner = _Inner()
    inner.fail = LLMError("cut off", reason="output_cap")
    worker = _worker(tmp_path, inner)
    with pytest.raises(LLMError):
        worker.complete_json(instructions="ins", document_text=PRIVATE)
    ((event, _level, fields),) = events
    assert event == "llm_request_failed" and fields["reason"] == "output_cap"
    assert PRIVATE not in json.dumps(fields)


def test_a_slow_or_long_request_warns_once_per_stage(tmp_path: Path, events: list) -> None:
    worker = _worker(tmp_path, _Inner())
    worker._stage = "cleanup"
    for _ in range(6):
        worker._observe(2.0)
    worker._observe(900.0)
    worker._observe(950.0)
    warnings = [item for item in events if item[0] == "llm_slow_request"]
    assert len(warnings) == 1 and warnings[0][1] == logging.WARNING
    assert warnings[0][2]["stage"] == "cleanup" and warnings[0][2]["seconds"] == 900.0
    worker._stage = "narration"
    worker.provider.last_usage = {"prompt_tokens": 1, "completion_tokens": 30}
    for _ in range(6):
        worker._observe(2.0)
    worker.provider.last_usage = {"prompt_tokens": 1, "completion_tokens": 40000}
    worker._observe(2.0)
    assert [item[2]["stage"] for item in events if item[0] == "llm_slow_request"] == [
        "cleanup",
        "narration",
    ]


def test_ordinary_variation_does_not_warn(tmp_path: Path, events: list) -> None:
    worker = _worker(tmp_path, _Inner())
    worker._stage = "cleanup"
    for seconds in (2, 3, 2, 4, 3, 5, 6):
        worker._observe(float(seconds))
    assert [item for item in events if item[0] == "llm_slow_request"] == []


@pytest.mark.parametrize(
    "body",
    [
        {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]},
        {"choices": [{"message": {"content": '{"a": '}, "finish_reason": "length"}]},
    ],
)
def test_both_output_cap_failures_carry_the_reason(body: dict[str, Any]) -> None:
    provider = OpenAICompatibleProvider(
        provider="ollama",
        base_url="http://127.0.0.1:11434/v1",
        model="local",
        allow_remote=False,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)),
        max_context_tokens=4096,
        max_output_tokens=100,
    )
    with provider as client, pytest.raises(LLMError) as raised:
        client.complete_json(instructions="x", document_text="y")
    assert raised.value.reason == "output_cap"
