"""An explicit, executable record of an unresolved completed-audio reuse limitation."""

import pytest
from test_voice_cloning_conversion import app, runner
from test_voice_cloning_conversion import cloned_book as cloned_book


@pytest.fixture(autouse=True)
def installed_backend(monkeypatch):
    monkeypatch.setattr("pdf2audiobook.tts.cloning.package_versions", lambda: {"torch": "2.6.0"})


@pytest.mark.xfail(
    strict=True,
    reason="VC5.05: retained reference triggers synthesis after optional backend removal",
)
def test_finished_audio_reuses_without_sdk_while_reference_exists(cloned_book, monkeypatch):
    book = cloned_book
    before = len(book["calls"])
    monkeypatch.setattr("pdf2audiobook.tts.cloning.package_versions", lambda: {})
    result = runner.invoke(app, book["args"])
    assert result.exit_code == 0, result.output
    assert len(book["calls"]) == before
