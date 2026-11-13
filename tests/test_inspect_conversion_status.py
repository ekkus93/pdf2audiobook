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


def test_status_that_grows_before_it_is_read_is_reported_oversized(tmp_path, monkeypatch):
    manifest_path = _status_workspace(tmp_path, b'{"chapters": []}')
    real_open = Path.open

    def growing_open(self, *args, **kwargs):
        # The file is small for any size check made before this point and
        # grows past the limit just before the reading handle is opened.
        mode = args[0] if args else kwargs.get("mode", "r")
        if self.name == "conversion_status.json" and "r" in mode:
            with real_open(self, "wb") as stream:
                stream.write(_OVERSIZED_STATUS)
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", growing_open)

    result = CliRunner().invoke(app, ["inspect", str(manifest_path), "--json"])

    assert result.exit_code == 3, "an oversized status read must not be silently omitted"
    error = json.loads(result.stderr)
    assert error["error"]["message"] == "Conversion status file exceeds safe size limit"
    _assert_content_free(result.stderr, tmp_path)


def test_status_that_grows_between_open_and_read_is_reported_oversized(tmp_path, monkeypatch):
    manifest_path = _status_workspace(tmp_path, b'{"chapters": []}')
    real_open = Path.open
    read_opens = []

    class _GrowsOnFirstRead:
        """Delegates to the real handle; the file grows just before the first read."""

        def __init__(self, handle, path):
            self._handle = handle
            self._path = path
            self._grown = False

        def read(self, *args, **kwargs):
            if not self._grown:
                self._grown = True
                with real_open(self._path, "ab") as stream:
                    stream.write(b" " * (_STATUS_LIMIT + 1))
            return self._handle.read(*args, **kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            self._handle.close()

        def __getattr__(self, name):
            return getattr(self._handle, name)

    def growing_open(self, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        handle = real_open(self, *args, **kwargs)
        if self.name == "conversion_status.json" and "r" in mode:
            read_opens.append(self)
            return _GrowsOnFirstRead(handle, self)
        return handle

    monkeypatch.setattr(Path, "open", growing_open)

    result = CliRunner().invoke(app, ["inspect", str(manifest_path), "--json"])

    # Any size check made after opening but before reading (fstat, seek) sees
    # the small file; only a decision from the bytes read reports the growth.
    assert result.exit_code == 3, "an oversized status read must not be silently omitted"
    error = json.loads(result.stderr)
    assert error["error"]["message"] == "Conversion status file exceeds safe size limit"
    _assert_content_free(result.stderr, tmp_path)
    assert len(read_opens) == 1, "the status file must be read through a single handle"


def test_valid_status_is_read_through_a_single_handle(tmp_path, monkeypatch):
    status = json.dumps({"chapters": [{"number": 1, "status": "complete"}]}).encode()
    manifest_path = _status_workspace(tmp_path, status)
    real_open = Path.open
    read_opens = []

    def counting_open(self, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if self.name == "conversion_status.json" and "r" in mode:
            read_opens.append(self)
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counting_open)

    result = CliRunner().invoke(app, ["inspect", str(manifest_path), "--json"])

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["conversion_status"]["chapters"][0]["status"] == "complete"
    # The size decision and the parse must use the same bytes, from one handle.
    assert len(read_opens) == 1


def test_status_one_byte_over_the_limit_is_a_fixed_error_in_human_mode(tmp_path):
    status = b"{}" + b" " * (_STATUS_LIMIT - 1)
    assert len(status) == _STATUS_LIMIT + 1
    manifest_path = _status_workspace(tmp_path, status)

    result = CliRunner().invoke(app, ["inspect", str(manifest_path)])

    assert result.exit_code == 3
    assert result.stderr.lstrip().startswith("Error:")
    assert "Conversion status file exceeds safe size limit" in result.stderr
    _assert_content_free(result.stderr, tmp_path)


def test_unavailable_synthesis_progress_uses_null_report_fields():
    from pdf2audiobook.pipeline import _progress_report_fields

    assert _progress_report_fields(None) == (None, None)
    assert _progress_report_fields({"mapping": None}) == (None, None)


# Literal sizes, so a change to the shared constant cannot move both sides of a
# boundary test at once (spec R1: exactly 1 MiB).
_ONE_MIB = 1_048_576


def test_the_status_limit_is_exactly_one_mebibyte(tmp_path):
    body = json.dumps({"chapters": [{"number": 1, "status": "complete"}]}).encode()
    at_limit = body + b" " * (_ONE_MIB - len(body))
    assert len(at_limit) == _ONE_MIB
    included = CliRunner().invoke(
        app, ["inspect", str(_status_workspace(tmp_path / "at", at_limit)), "--json"]
    )
    over = CliRunner().invoke(
        app, ["inspect", str(_status_workspace(tmp_path / "over", at_limit + b" ")), "--json"]
    )

    assert included.exit_code == 0, included.stderr
    assert json.loads(included.stdout)["conversion_status"]["chapters"][0]["number"] == 1
    assert over.exit_code == 3
    assert json.loads(over.stderr)["error"]["message"] == (
        "Conversion status file exceeds safe size limit"
    )


class _ReplacedRead:
    """Delegates to the real handle but returns `payload` from the first read, then
    runs `after_read`, so the bytes read and the file on disk can disagree."""

    def __init__(self, handle, payload, after_read=None):
        self._handle = handle
        self._payload = payload
        self._after_read = after_read

    def read(self, size=-1):
        data = self._payload if size < 0 else self._payload[:size]
        if self._after_read is not None:
            self._after_read()
        return data

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self._handle.close()

    def __getattr__(self, name):
        return getattr(self._handle, name)


def _replace_status_read(monkeypatch, payload, after_read=None):
    real_open = Path.open

    def replaced_open(self, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        handle = real_open(self, *args, **kwargs)
        if self.name == "conversion_status.json" and "r" in mode:
            return _ReplacedRead(handle, payload, after_read)
        return handle

    monkeypatch.setattr(Path, "open", replaced_open)


def test_oversize_is_decided_by_the_bytes_read_not_the_file_on_disk(tmp_path, monkeypatch):
    manifest_path = _status_workspace(tmp_path, b"{}")
    _replace_status_read(monkeypatch, _OVERSIZED_STATUS)

    result = CliRunner().invoke(app, ["inspect", str(manifest_path), "--json"])

    # The file on disk is two bytes; only the read shows it oversized.
    assert result.exit_code == 3
    assert json.loads(result.stderr)["error"]["message"] == (
        "Conversion status file exceeds safe size limit"
    )
    _assert_content_free(result.stderr, tmp_path)


def test_a_file_replaced_after_a_small_read_is_judged_by_what_was_read(tmp_path, monkeypatch):
    manifest_path = _status_workspace(tmp_path, b"{not json")
    status_path = tmp_path / "reports" / "conversion_status.json"

    def replace_with_a_large_file():
        status_path.write_bytes(_OVERSIZED_STATUS)

    _replace_status_read(monkeypatch, b"{not json", replace_with_a_large_file)

    result = CliRunner().invoke(app, ["inspect", str(manifest_path), "--json"])

    # The bytes read were small and malformed: omitted, never reported oversized.
    assert result.exit_code == 0, result.stderr
    assert "conversion_status" not in json.loads(result.stdout)
    assert "exceeds safe size limit" not in result.stderr


def test_status_is_read_in_binary_and_bounded_in_bytes(tmp_path, monkeypatch):
    manifest_path = _status_workspace(tmp_path, b"{}")
    real_open = Path.open
    reads = []

    def recording_open(self, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if self.name == "conversion_status.json" and "r" in mode:
            reads.append(mode)
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", recording_open)

    result = CliRunner().invoke(app, ["inspect", str(manifest_path), "--json"])

    assert result.exit_code == 0, result.stderr
    # A text-mode read of limit + 1 characters could pull in about 4 MiB.
    assert reads == ["rb"]


def test_status_nested_exactly_sixteen_deep_is_included(tmp_path):
    status = b'{"a":' * 15 + b"{}" + b"}" * 15
    manifest_path = _status_workspace(tmp_path, status)

    result = CliRunner().invoke(app, ["inspect", str(manifest_path), "--json"])

    assert result.exit_code == 0, result.stderr
    assert "a" in json.loads(result.stdout)["conversion_status"]


def test_unreadable_conversion_status_is_omitted_in_human_mode(tmp_path, monkeypatch):
    manifest_path = _status_workspace(tmp_path, b"{}")
    real_open = Path.open

    def denied_open(self, *args, **kwargs):
        if self.name == "conversion_status.json":
            raise PermissionError(13, "Permission denied", str(self))
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied_open)

    result = CliRunner().invoke(app, ["inspect", str(manifest_path)])

    assert result.exit_code == 0, result.stderr
    assert "Permission denied" not in result.output
    _assert_content_free(result.output, tmp_path)
