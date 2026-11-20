"""Finished clone audio resumes without the optional backend while its reference remains (VC5.05)."""

import pytest
from test_voice_cloning_conversion import app, runner
from test_voice_cloning_conversion import cloned_book as cloned_book
from test_voice_cloning_vc505 import constructed as constructed  # noqa: F401


@pytest.fixture(autouse=True)
def installed_backend(monkeypatch):
    monkeypatch.setattr("pdf2audiobook.tts.cloning.package_versions", lambda: {"torch": "2.6.0"})


def test_finished_audio_reuses_without_sdk_while_reference_exists(
    cloned_book, constructed, monkeypatch
):
    book = cloned_book
    before = len(book["calls"])
    monkeypatch.setattr("pdf2audiobook.tts.cloning.package_versions", lambda: {})
    result = runner.invoke(app, book["args"])
    assert result.exit_code == 0, result.output
    assert len(book["calls"]) == before
    assert constructed == []
