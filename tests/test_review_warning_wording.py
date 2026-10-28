"""The analysis warning summary says what it counts, not what it blocks (F4)."""

import logging

import pytest

from pdf2audiobook import logging as app_logging


@pytest.fixture
def human_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_logging, "_CLI_ACTIVE", True)
    monkeypatch.setattr(app_logging, "_OUTPUT_MODE", "human")
    monkeypatch.setattr(app_logging, "_VERBOSE", False)
    monkeypatch.setattr(app_logging, "_EXPLICIT_LOG_LEVEL", False)
    monkeypatch.setattr(app_logging, "_QUIET", False)
    monkeypatch.setattr(app_logging, "_WARNING_CODES", [])


def _emit(fields: dict[str, object]) -> None:
    app_logging._dispatch("review_warning", logging.WARNING, fields)


@pytest.mark.usefixtures("human_mode")
@pytest.mark.parametrize(
    ("count", "line"),
    [
        (398, "Warning: Analysis recorded 398 warnings; see warnings in manifest.json.\n"),
        (2, "Warning: Analysis recorded 2 warnings; see warnings in manifest.json.\n"),
        (1, "Warning: Analysis recorded 1 warning; see warnings in manifest.json.\n"),
    ],
)
def test_a_counted_summary_names_the_count_and_where_to_look(
    capsys: pytest.CaptureFixture[str], count: int, line: str
) -> None:
    _emit({"stage": "analysis", "count": count})
    assert capsys.readouterr().err == line


@pytest.mark.usefixtures("human_mode")
def test_the_empty_chapter_warning_keeps_its_review_wording(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _emit({"reason": "empty_chapter_requires_approval"})
    assert capsys.readouterr().err == "Warning: Book review is required before conversion.\n"


@pytest.mark.usefixtures("human_mode")
@pytest.mark.parametrize("count", [True, "3", 0, -1])
def test_an_unusable_count_falls_back_to_the_review_wording(
    capsys: pytest.CaptureFixture[str], count: object
) -> None:
    _emit({"stage": "analysis", "count": count})
    assert capsys.readouterr().err == "Warning: Book review is required before conversion.\n"


@pytest.mark.usefixtures("human_mode")
def test_the_event_code_is_unchanged_for_machine_readers() -> None:
    _emit({"stage": "analysis", "count": 5})
    assert app_logging._WARNING_CODES == ["review_warning"]
