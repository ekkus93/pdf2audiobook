"""User-facing progress and time estimates.

Pipeline code depends only on ``ProgressReporter``; only this module imports
``tqdm``. Descriptions and details are limited to stage names, counts and chapter
numbers so that progress output never discloses book text, titles or paths.
"""

from __future__ import annotations

import os
import sys
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
