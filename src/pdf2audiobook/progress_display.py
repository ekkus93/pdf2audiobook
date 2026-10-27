"""User-facing progress and time estimates.

Pipeline code depends only on ``ProgressReporter``; only this module imports
``tqdm``. Descriptions and details are limited to stage names, counts and chapter
numbers so that progress output never discloses book text, titles or paths.
"""

from __future__ import annotations

import contextlib
import contextvars
import os
import sys
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, Protocol

_DETERMINATE_WAITING = (
    "{desc}{postfix}: {n_fmt}/{total_fmt} {unit} [{elapsed} elapsed, estimating…]"
)
_DETERMINATE = (
    "{desc}{postfix}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} {unit} "
    "[{elapsed} elapsed, {remaining} left]"
)
_INDETERMINATE = "{desc}{postfix}: {n_fmt} {unit} [{elapsed} elapsed]"

# Open tqdm bars; log lines are routed through tqdm.write while any is open.
_open_bars = 0


class ProgressHandle(Protocol):
    def advance(self, count: int = 1, *, cached: bool = False) -> None:
        """Record finished units; ``cached`` units complete instantly and skip the rate."""

    def set_total(self, total: int) -> None: ...

    def set_detail(self, text: str) -> None: ...

    def close(self) -> None: ...


class ProgressReporter(Protocol):
    enabled: bool

    def stage(
        self, name: str, total: int | None, unit: str, initial: int = 0
    ) -> ProgressHandle: ...

    def summary(self, text: str) -> None: ...

    def close(self) -> None: ...


class _NullHandle:
    def advance(self, count: int = 1, *, cached: bool = False) -> None:
        return None

    def set_total(self, total: int) -> None:
        return None

    def set_detail(self, text: str) -> None:
        return None

    def close(self) -> None:
        return None


class NullReporter:
    """Shows nothing; the default for library use, ``--json``, ``--quiet`` and pipes."""

    enabled = False

    def stage(self, name: str, total: int | None, unit: str, initial: int = 0) -> ProgressHandle:
        return _NullHandle()

    def summary(self, text: str) -> None:
        return None

    def close(self) -> None:
        return None


class _TqdmHandle:
    def __init__(self, reporter: TqdmReporter, bar: Any, total: int | None) -> None:
        self._reporter = reporter
        self._bar = bar
        self._real_work = False
        self._closed = False
        self._apply_format(total)

    def _apply_format(self, total: int | None) -> None:
        if total is None:
            self._bar.bar_format = _INDETERMINATE
        elif self._real_work:
            self._bar.bar_format = _DETERMINATE
        else:
            self._bar.bar_format = _DETERMINATE_WAITING

    def advance(self, count: int = 1, *, cached: bool = False) -> None:
        if self._closed or count <= 0:
            return
        bar = self._bar
        if cached:
            # Instant work must not look like fast work: move the counters and the
            # rate baseline together so only real units feed the estimate.
            bar.n += count
            bar.initial += count
            bar.last_print_n += count
            bar.refresh()
            return
        if not self._real_work:
            # Switch before the redraw so the first real unit already shows an estimate.
            self._real_work = True
            self._apply_format(bar.total)
        bar.update(count)

    def set_total(self, total: int) -> None:
        if self._closed or total <= 0:
            return
        self._bar.total = max(total, self._bar.n)
        self._apply_format(self._bar.total)
        self._bar.refresh()

    def set_detail(self, text: str) -> None:
        if not self._closed:
            self._bar.set_postfix_str(text, refresh=True)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._bar.close()
        self._reporter._forget(self)


class TqdmReporter:
    """Draw tqdm bars with an estimate that waits for the first real unit of work."""

    enabled = True

    def __init__(self, stream: IO[str] | None = None, *, min_interval: float = 0.25) -> None:
        self._stream = stream if stream is not None else sys.stderr
        self._min_interval = min_interval
        self._handles: list[_TqdmHandle] = []

    def stage(self, name: str, total: int | None, unit: str, initial: int = 0) -> ProgressHandle:
        global _open_bars
        from tqdm import tqdm

        # A pseudo-terminal can report a 0x0 size, and tqdm then draws nothing at all.
        known_width = _terminal_size(self._stream) is not None
        bar = tqdm(
            total=total,
            initial=initial,
            desc=name,
            unit=unit,
            file=self._stream,
            dynamic_ncols=known_width,
            ncols=None if known_width else 100,
            nrows=None if known_width else 24,
            mininterval=self._min_interval,
            miniters=1 if self._min_interval == 0 else None,
            bar_format=_INDETERMINATE if total is None else _DETERMINATE_WAITING,
            leave=True,
        )
        handle = _TqdmHandle(self, bar, total)
        self._handles.append(handle)
        _open_bars += 1
        return handle

    def _forget(self, handle: _TqdmHandle) -> None:
        global _open_bars
        if handle in self._handles:
            self._handles.remove(handle)
            _open_bars = max(0, _open_bars - 1)

    def summary(self, text: str) -> None:
        from tqdm import tqdm

        tqdm.write(text, file=self._stream)

    def close(self) -> None:
        for handle in list(self._handles):
            handle.close()


def _terminal_size(stream: IO[str]) -> tuple[int, int] | None:
    """(columns, rows) of the terminal behind ``stream``; None when unknown or reported as 0."""
    try:
        size = os.get_terminal_size(stream.fileno())
    except (AttributeError, ValueError, OSError):
        return None
    return (size.columns, size.lines) if size.columns > 0 and size.lines > 0 else None


def make_reporter(
    mode: str, *, json_output: bool, quiet: bool, stream: IO[str] | None = None
) -> ProgressReporter:
    """Choose a reporter: never under ``--json``/``--quiet``; ``auto`` needs a terminal."""
    if json_output or quiet or mode == "never":
        return NullReporter()
    target = stream if stream is not None else sys.stderr
    if mode == "always":
        return TqdmReporter(target)
    try:
        interactive = bool(target.isatty())
    except (AttributeError, ValueError, OSError):
        interactive = False
    return TqdmReporter(target) if interactive else NullReporter()


def bars_active() -> bool:
    return _open_bars > 0


def write_stderr(text: str) -> None:
    """Write a log line without corrupting an active bar."""
    if _open_bars > 0:
        from tqdm import tqdm

        tqdm.write(text.rstrip("\n"), file=sys.stderr)
    else:
        sys.stderr.write(text)


def format_elapsed(seconds: float) -> str:
    """Render a duration such as ``41m 07s`` for completion summaries."""
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


_current: contextvars.ContextVar[ProgressReporter | None] = contextvars.ContextVar(
    "pdf2audiobook_progress", default=None
)


def current_reporter() -> ProgressReporter:
    """The reporter the running command installed, or a silent one."""
    return _current.get() or NullReporter()


@contextlib.contextmanager
def use_reporter(reporter: ProgressReporter) -> Iterator[None]:
    """Make ``reporter`` the default for pipeline calls that are not given one."""
    token = _current.set(reporter)
    try:
        yield
    finally:
        _current.reset(token)


def bind_workspace(reporter: ProgressReporter, folder: Path) -> None:
    """Tell a reporter that keeps a status file where the workspace is (optional)."""
    bind = getattr(reporter, "bind_workspace", None)
    if callable(bind):
        bind(folder)


class _StatusHandle:
    def __init__(
        self,
        owner: StatusReporter,
        inner: ProgressHandle,
        name: str,
        unit: str,
        total: int | None,
        initial: int,
    ) -> None:
        self._owner = owner
        self._inner = inner
        self.name, self.unit, self.total = name, unit, total
        self.detail = ""
        self.done = initial
        self.cached = initial
        self.started = time.monotonic()
        self.closed = False

    def advance(self, count: int = 1, *, cached: bool = False) -> None:
        self._inner.advance(count, cached=cached)
        with self._owner._lock:
            self.done += count
            if cached:
                self.cached += count
        self._owner._write(force=False)

    def set_total(self, total: int) -> None:
        self._inner.set_total(total)
        with self._owner._lock:
            self.total = max(total, self.done)

    def set_detail(self, text: str) -> None:
        self._inner.set_detail(text)
        with self._owner._lock:
            self.detail = text

    def close(self) -> None:
        self._inner.close()
        self._owner._finish_stage(self)

    def snapshot(self) -> dict[str, Any]:
        elapsed = time.monotonic() - self.started
        real = self.done - self.cached
        remaining = None
        if self.total is not None and real > 0 and elapsed > 0:
            remaining = round(max(0, self.total - self.done) / (real / elapsed))
        return {
            "name": self.name,
            "detail": self.detail,
            "unit": self.unit,
            "done": self.done,
            "total": self.total,
            "elapsed_seconds": round(elapsed),
            "estimated_remaining_seconds": remaining,
        }


class StatusReporter:
    """Wrap a reporter to keep ``reports/run_status.json`` and an optional heartbeat.

    Both carry only stage names, counts, chapter numbers and times, so they are safe
    under ``--json`` and for tailing from another terminal. A background tick keeps the
    file fresh even while one long LLM request blocks the main thread.
    """

    enabled = True

    def __init__(
        self,
        inner: ProgressReporter,
        *,
        command: str,
        heartbeat_seconds: float = 0.0,
        stream: IO[str] | None = None,
        tick_seconds: float = 5.0,
    ) -> None:
        self._inner = inner
        self._command = command
        self._heartbeat = heartbeat_seconds
        self._stream = stream
        self._lock = threading.RLock()
        self._path: Path | None = None
        self._started = time.monotonic()
        self._started_at = datetime.now(UTC)
        self._active: _StatusHandle | None = None
        self._finished: list[dict[str, Any]] = []
        self._state = "running"
        self._last_write = 0.0
        self._stop = threading.Event()
        self._tick = min(tick_seconds, heartbeat_seconds) if heartbeat_seconds > 0 else tick_seconds
        self._thread: threading.Thread | None = None
        self._next_beat = time.monotonic() + heartbeat_seconds

    def bind_workspace(self, folder: Path) -> None:
        with self._lock:
            self._path = folder / "reports" / "run_status.json"
        self._write(force=True)
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="progress-status", daemon=True)
            self._thread.start()

    def stage(self, name: str, total: int | None, unit: str, initial: int = 0) -> ProgressHandle:
        handle = _StatusHandle(
            self, self._inner.stage(name, total, unit, initial), name, unit, total, initial
        )
        with self._lock:
            self._active = handle
        self._write(force=True)
        return handle

    def _finish_stage(self, handle: _StatusHandle) -> None:
        with self._lock:
            if handle.closed:
                return
            handle.closed = True
            self._finished.append(
                {"name": handle.name, "seconds": round(time.monotonic() - handle.started)}
            )
            if self._active is handle:
                self._active = None
        self._write(force=True)

    def summary(self, text: str) -> None:
        with self._lock:
            self._state = "completed"
        self._inner.summary(text)
        self._write(force=True)

    def close(self) -> None:
        self._inner.close()
        with self._lock:
            if self._state == "running":
                self._state = "stopped"
            if self._active is not None and not self._active.closed:
                self._active = None
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._write(force=True)

    def _payload(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema_version": 1,
                "command": self._command,
                "state": self._state,
                "started_at": self._started_at.isoformat(timespec="seconds"),
                "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "elapsed_seconds": round(time.monotonic() - self._started),
                "stage": self._active.snapshot() if self._active is not None else None,
                "completed_stages": list(self._finished),
            }

    def _write(self, *, force: bool) -> None:
        now = time.monotonic()
        with self._lock:
            path = self._path
            if path is None or (not force and now - self._last_write < 2.0):
                return
            self._last_write = now
        try:
            from pdf2audiobook.workspace import write_json

            write_json(path, self._payload())
        except Exception:
            # Status reporting must never fail a conversion.
            return

    def heartbeat_line(self) -> str:
        payload = self._payload()
        stage = payload["stage"]
        clock = datetime.now().strftime("%H:%M:%S")
        elapsed = format_elapsed(payload["elapsed_seconds"])
        if stage is None:
            return f"[{clock}] {self._command}: working, {elapsed} elapsed"
        count = f"{stage['done']}/{stage['total']}" if stage["total"] else str(stage["done"])
        label = stage["name"] + (f", {stage['detail']}" if stage["detail"] else "")
        eta = stage["estimated_remaining_seconds"]
        tail = f", about {format_elapsed(eta)} left" if eta is not None else ""
        return f"[{clock}] {label}: {count} {stage['unit']}, {elapsed} elapsed{tail}"

    def _run(self) -> None:
        while not self._stop.wait(self._tick):
            self._write(force=True)
            if self._heartbeat > 0 and time.monotonic() >= self._next_beat:
                self._next_beat = time.monotonic() + self._heartbeat
                line = self.heartbeat_line() + "\n"
                if self._stream is not None:
                    self._stream.write(line)
                    self._stream.flush()
                else:
                    write_stderr(line)
