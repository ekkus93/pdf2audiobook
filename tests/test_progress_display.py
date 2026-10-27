"""Progress bars show stages, counts and an honest estimate without leaking content (R11)."""

import io
import re

import pytest

from pdf2audiobook import progress_display
from pdf2audiobook.progress_display import (
    NullReporter,
    TqdmReporter,
    bars_active,
    format_elapsed,
    make_reporter,
    write_stderr,
)

PRIVATE = "PrivateBookSentence"


@pytest.fixture(autouse=True)
def _no_leaked_bars():
    progress_display._open_bars = 0
    yield
    progress_display._open_bars = 0


class FakeTTY(io.StringIO):
    def isatty(self) -> bool:
        return True


def _plain(stream: io.StringIO) -> str:
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", stream.getvalue()).replace("\r", "\n")


@pytest.mark.parametrize(
    ("mode", "json_output", "quiet", "tty", "expected"),
    [
        ("auto", False, False, True, TqdmReporter),
        ("auto", False, False, False, NullReporter),
        ("always", False, False, False, TqdmReporter),
        ("never", False, False, True, NullReporter),
        ("always", True, False, True, NullReporter),
        ("always", False, True, True, NullReporter),
        ("auto", True, False, True, NullReporter),
    ],
)
def test_reporter_choice(mode, json_output, quiet, tty, expected):
    stream = FakeTTY() if tty else io.StringIO()
    reporter = make_reporter(mode, json_output=json_output, quiet=quiet, stream=stream)
    assert type(reporter) is expected
    assert reporter.enabled is (expected is TqdmReporter)


def test_null_reporter_accepts_every_call():
    reporter = NullReporter()
    handle = reporter.stage("Anything", 3, "unit", initial=1)
    handle.advance()
    handle.advance(2, cached=True)
    handle.set_total(9)
    handle.set_detail("chapter 1/2")
    handle.close()
    reporter.summary("done")
    reporter.close()


def test_bar_shows_stage_count_and_waits_for_real_work_before_estimating():
    stream = FakeTTY()
    reporter = TqdmReporter(stream, min_interval=0)
    handle = reporter.stage("Synthesis", 100, "char")
    handle.set_detail("chapter 1/2")
    assert bars_active()
    first = _plain(stream)
    assert "Synthesis" in first and "0/100" in first and "chapter 1/2" in first
    assert "estimating" in first and "left" not in first
    handle.advance(20)
    later = _plain(stream)
    assert "20/100" in later and "left" in later
    handle.close()
    assert not bars_active()


def test_cached_units_move_the_count_but_not_the_rate_baseline():
    stream = FakeTTY()
    reporter = TqdmReporter(stream, min_interval=0)
    handle = reporter.stage("Synthesis", 100, "char", initial=10)
    handle.advance(40, cached=True)
    text = _plain(stream)
    assert "50/100" in text and "estimating" in text
    bar = handle._bar  # type: ignore[attr-defined]
    assert bar.n == 50 and bar.initial == 50
    handle.advance(5)
    assert "55/100" in _plain(stream)
    assert bar.n - bar.initial == 5
    reporter.close()
    assert not bars_active()


def test_unknown_total_shows_elapsed_time_without_an_estimate():
    stream = FakeTTY()
    reporter = TqdmReporter(stream, min_interval=0)
    handle = reporter.stage("Analysis", None, "request")
    handle.advance(3)
    text = _plain(stream)
    assert "3 request" in text and "elapsed" in text
    assert "left" not in text and "estimating" not in text
    handle.set_total(10)
    handle.advance(1)
    assert "4/10" in _plain(stream)
    reporter.close()


def test_total_never_drops_below_the_current_count():
    reporter = TqdmReporter(FakeTTY(), min_interval=0)
    handle = reporter.stage("Analysis", 5, "request")
    handle.advance(4)
    handle.set_total(2)
    assert handle._bar.total == 4  # type: ignore[attr-defined]
    reporter.close()


def test_output_contains_only_stage_names_and_counts():
    stream = FakeTTY()
    reporter = TqdmReporter(stream, min_interval=0)
    handle = reporter.stage("Synthesis", 10, "char")
    handle.set_detail("chapter 2/3")
    handle.advance(4)
    reporter.summary("Converted 3 chapters in 4s")
    reporter.close()
    text = _plain(stream)
    assert PRIVATE not in text and "/tmp" not in text
    assert "Converted 3 chapters in 4s" in text


def test_closing_twice_and_advancing_after_close_is_harmless():
    reporter = TqdmReporter(FakeTTY(), min_interval=0)
    handle = reporter.stage("Stage", 2, "unit")
    handle.close()
    handle.close()
    handle.advance()
    handle.set_detail("late")
    reporter.close()
    assert not bars_active()


def test_log_lines_go_through_tqdm_while_a_bar_is_open(capsys):
    import sys

    reporter = TqdmReporter(sys.stderr, min_interval=0)
    handle = reporter.stage("Stage", 2, "unit")
    write_stderr("a log line\n")
    handle.close()
    write_stderr("after\n")
    err = capsys.readouterr().err
    assert "a log line" in err and "after\n" in err
    assert progress_display._open_bars == 0


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(0, "0s"), (7, "7s"), (59.6, "1m 00s"), (2467, "41m 07s"), (3723, "1h 02m 03s")],
)
def test_format_elapsed(seconds, text):
    assert format_elapsed(seconds) == text
