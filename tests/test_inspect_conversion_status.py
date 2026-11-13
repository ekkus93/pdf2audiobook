"""Inspect reports persistent failed chapter status alongside the manifest."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import CONVERSION_STATUS_MAX_BYTES, app
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock
from pdf2audiobook.workspace import write_manifest


def test_inspect_json_includes_failed_chapter_report(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    write_manifest(
        manifest_path,
        BookManifest(
            schema_version=3,
            input_sha256="a" * 64,
            title="Synthetic",
            source_path="book.pdf",
            blocks=[DocumentBlock(id="b1", page_index=0, text="Text.")],
            chapters=[
                Chapter(id="c1", number=1, title="One", start_block=0, end_block=1, confidence=1)
            ],
        ),
    )
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "conversion_status.json").write_text(
        json.dumps({"chapters": [{"number": 1, "status": "failed", "error_code": 7}]}),
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["inspect", str(manifest_path), "--json"])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["conversion_status"]["chapters"][0]["status"] == "failed"


def test_inspect_rejects_oversized_conversion_status_file(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    write_manifest(
        manifest_path,
        BookManifest(
            schema_version=3,
            input_sha256="a" * 64,
            title="Synthetic",
            source_path="book.pdf",
            blocks=[DocumentBlock(id="b1", page_index=0, text="Text.")],
            chapters=[
                Chapter(id="c1", number=1, title="One", start_block=0, end_block=1, confidence=1)
            ],
        ),
    )
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "conversion_status.json").write_bytes(b"{}" + b" " * (1024 * 1024))

    result = CliRunner().invoke(app, ["inspect", str(manifest_path), "--json"])
    assert result.exit_code == 3
    error = json.loads(result.stderr)
    assert error["error"]["message"] == "Conversion status file exceeds safe size limit"


_STATUS_LIMIT = CONVERSION_STATUS_MAX_BYTES
_OVERSIZED_STATUS = b"{}" + b" " * _STATUS_LIMIT


def _status_workspace(tmp_path, status: bytes | None):
    manifest_path = tmp_path / "manifest.json"
    write_manifest(
        manifest_path,
        BookManifest(
            schema_version=3,
            input_sha256="a" * 64,
            title="Synthetic",
            source_path="book.pdf",
            blocks=[DocumentBlock(id="b1", page_index=0, text="Text.")],
            chapters=[
                Chapter(id="c1", number=1, title="One", start_block=0, end_block=1, confidence=1)
            ],
        ),
    )
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    if status is not None:
        (report_dir / "conversion_status.json").write_bytes(status)
    return manifest_path


def _assert_content_free(output: str, tmp_path) -> None:
    assert str(tmp_path) not in output
    assert "conversion_status.json" not in output
    assert "errno" not in output.lower()


def test_oversized_conversion_status_in_human_mode_is_a_fixed_error(tmp_path):
    manifest_path = _status_workspace(tmp_path, _OVERSIZED_STATUS)

    result = CliRunner().invoke(app, ["inspect", str(manifest_path)])

    assert result.exit_code == 3
    assert result.stderr.lstrip().startswith("Error:")
    assert "Conversion status file exceeds safe size limit" in result.stderr
    _assert_content_free(result.stderr, tmp_path)


def test_oversized_conversion_status_json_error_is_one_content_free_value(tmp_path):
    manifest_path = _status_workspace(tmp_path, _OVERSIZED_STATUS)

    result = CliRunner().invoke(app, ["inspect", str(manifest_path), "--json"])

    assert result.exit_code == 3
    error = json.loads(result.stderr)
    assert error["error"]["message"] == "Conversion status file exceeds safe size limit"
    assert result.stdout == ""
    _assert_content_free(result.stderr, tmp_path)


def test_conversion_status_of_exactly_the_limit_is_included(tmp_path):
    body = json.dumps({"chapters": [{"number": 1, "status": "complete"}]}).encode()
    status = body + b" " * (_STATUS_LIMIT - len(body))
    assert len(status) == _STATUS_LIMIT
    manifest_path = _status_workspace(tmp_path, status)

    result = CliRunner().invoke(app, ["inspect", str(manifest_path), "--json"])

    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["conversion_status"]["chapters"][0]["status"] == "complete"


@pytest.mark.parametrize(
    "status",
    [
        None,
        b"{not json",
        b'"a string, not an object"',
        b"[" * 17 + b"]" * 17,
        b'{"a":' * 17 + b"1" + b"}" * 17,
    ],
    ids=["missing", "malformed", "non-object", "over-depth-list", "over-depth-object"],
)
def test_missing_malformed_and_over_depth_status_is_omitted_not_oversized(tmp_path, status):
    manifest_path = _status_workspace(tmp_path, status)

    result = CliRunner().invoke(app, ["inspect", str(manifest_path), "--json"])

    assert result.exit_code == 0, result.stderr
    assert "conversion_status" not in json.loads(result.stdout)
    assert "exceeds safe size limit" not in result.stderr


def test_unreadable_conversion_status_is_omitted(tmp_path, monkeypatch):
    manifest_path = _status_workspace(tmp_path, b"{}")
    real_stat, real_open = Path.stat, Path.open

    def denied_stat(self, *args, **kwargs):
        if self.name == "conversion_status.json":
            raise PermissionError(13, "Permission denied", str(self))
        return real_stat(self, *args, **kwargs)

    def denied_open(self, *args, **kwargs):
        if self.name == "conversion_status.json":
            raise PermissionError(13, "Permission denied", str(self))
        return real_open(self, *args, **kwargs)

    # An unreadable reports directory makes both stat() and open() fail.
    monkeypatch.setattr(Path, "stat", denied_stat)
    monkeypatch.setattr(Path, "open", denied_open)

    result = CliRunner().invoke(app, ["inspect", str(manifest_path), "--json"])

    assert result.exit_code == 0, result.stderr
    assert "conversion_status" not in json.loads(result.stdout)


def test_status_that_grows_after_a_size_observation_is_reported_oversized(tmp_path, monkeypatch):
    manifest_path = _status_workspace(tmp_path, _OVERSIZED_STATUS)
    real_stat = Path.stat

    class _SmallStat:
        st_size = 2

    def stale_stat(self, *args, **kwargs):
        # Simulates the file being small when its size is observed and
        # growing or being replaced before it is read.
        if self.name == "conversion_status.json":
            return _SmallStat()
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stale_stat)

    result = CliRunner().invoke(app, ["inspect", str(manifest_path), "--json"])

    assert result.exit_code == 3
    error = json.loads(result.stderr)
    assert error["error"]["message"] == "Conversion status file exceeds safe size limit"
    _assert_content_free(result.stderr, tmp_path)


def test_unavailable_synthesis_progress_uses_null_report_fields():
    from pdf2audiobook.pipeline import _progress_report_fields

    assert _progress_report_fields(None) == (None, None)
    assert _progress_report_fields({"mapping": None}) == (None, None)
