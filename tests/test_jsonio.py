"""Bounded shared JSON loading for untrusted cache files."""

from pathlib import Path

import pytest

from pdf2audiobook.jsonio import JSONTooLargeError, load_bounded_json, load_size_checked_json


def test_load_bounded_json_checks_size_depth_constants_and_bracket_strings(tmp_path):
    path = tmp_path / "cache.json"
    path.write_bytes(b'{"value":"[[[", "items":[1]}')
    assert load_bounded_json(path, max_bytes=100, max_depth=2) == {
        "value": "[[[",
        "items": [1],
    }
    assert load_bounded_json(path, max_bytes=10, max_depth=2) is None

    path.write_bytes(b"[[[[0]]]]")
    assert load_bounded_json(path, max_bytes=100, max_depth=3) is None
    path.write_bytes(b"[NaN]")
    assert load_bounded_json(path, max_bytes=100, max_depth=3) is None
    path.write_bytes(b"[1e999]")
    assert load_bounded_json(path, max_bytes=100, max_depth=3) is None


def test_load_bounded_json_rejects_extreme_nesting_without_recursion_error(tmp_path):
    path = tmp_path / "deep.json"
    path.write_bytes(b"[" * 100_000)
    assert load_bounded_json(path, max_bytes=200_000, max_depth=64) is None


def test_size_checked_json_raises_only_when_the_read_exceeds_the_limit(tmp_path):
    path = tmp_path / "status.json"
    path.write_bytes(b'{"a":1}')
    assert load_size_checked_json(path, max_bytes=7, max_depth=2) == {"a": 1}
    with pytest.raises(JSONTooLargeError):
        load_size_checked_json(path, max_bytes=6, max_depth=2)
    # The cache loader keeps treating an over-limit file as a miss.
    assert load_bounded_json(path, max_bytes=6, max_depth=2) is None

    for payload in (b"{not json", b"[[[1]]]", b"[NaN]"):
        path.write_bytes(payload)
        assert load_size_checked_json(path, max_bytes=100, max_depth=2) is None
    assert load_size_checked_json(tmp_path / "missing.json", max_bytes=100, max_depth=2) is None


def test_size_checked_json_closes_its_handle_on_every_path(tmp_path, monkeypatch):
    opened = []
    real_open = Path.open

    def tracking_open(self, *args, **kwargs):
        handle = real_open(self, *args, **kwargs)
        if handle.readable() and not handle.writable():
            opened.append(handle)
        return handle

    monkeypatch.setattr(Path, "open", tracking_open)
    path = tmp_path / "status.json"
    for payload, max_bytes in ((b'{"a":1}', 100), (b'{"a":1}', 3), (b"{bad", 100)):
        path.write_bytes(payload)
        try:
            load_size_checked_json(path, max_bytes=max_bytes, max_depth=2)
        except JSONTooLargeError:
            pass
    assert len(opened) == 3
    assert all(handle.closed for handle in opened)


class _RecordingHandle:
    """Wraps a real handle, records read sizes, and can return fixed bytes."""

    def __init__(self, handle, reads, payload=None):
        self._handle = handle
        self._reads = reads
        self._payload = payload

    def read(self, *args, **kwargs):
        size = args[0] if args else kwargs.get("size", -1)
        self._reads.append(size)
        if self._payload is not None:
            return self._payload[: size if size is not None and size >= 0 else None]
        return self._handle.read(*args, **kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self._handle.close()

    def __getattr__(self, name):
        return getattr(self._handle, name)


def _recording_open(monkeypatch, reads, payload=None):
    real_open = Path.open

    def recording_open(self, *args, **kwargs):
        handle = real_open(self, *args, **kwargs)
        mode = args[0] if args else kwargs.get("mode", "r")
        if self.name == "status.json" and "r" in mode:
            return _RecordingHandle(handle, reads, payload)
        return handle

    monkeypatch.setattr(Path, "open", recording_open)


def test_size_checked_json_reads_exactly_one_byte_past_the_limit(tmp_path, monkeypatch):
    path = tmp_path / "status.json"
    reads: list = []
    _recording_open(monkeypatch, reads)

    path.write_bytes(b'{"a":1}')
    assert load_size_checked_json(path, max_bytes=100, max_depth=2) == {"a": 1}
    path.write_bytes(b'{"a":"' + b"x" * 200 + b'"}')
    with pytest.raises(JSONTooLargeError):
        load_size_checked_json(path, max_bytes=100, max_depth=2)

    # One bounded read per load; never an unbounded or larger read.
    assert reads == [101, 101]


def test_size_checked_json_decides_from_the_bytes_read_not_the_file_size(tmp_path, monkeypatch):
    path = tmp_path / "status.json"
    path.write_bytes(b"{}")  # fstat reports 2 bytes
    reads: list = []
    _recording_open(monkeypatch, reads, payload=b" " * 101)

    with pytest.raises(JSONTooLargeError):
        load_size_checked_json(path, max_bytes=100, max_depth=2)
    assert reads == [101]


# --- Depth scan and bounds (test coverage round 2, U6) -------------------------


@pytest.mark.parametrize(
    ("payload", "value", "depth"),
    [
        (rb'{"k": "a\"]"}', {"k": 'a"]'}, 1),
        (rb'{"k": "a\"}"}', {"k": 'a"}'}, 1),
        (rb'["\\", [1]]', ["\\", [1]], 2),
        (rb'["\\\"[", [1]]', ['\\"[', [1]], 2),
        (rb'[{"k": "\\"}, "]]]"]', [{"k": "\\"}, "]]]"], 2),
    ],
    ids=[
        "escaped-quote-then-bracket",
        "escaped-quote-then-brace",
        "escaped-backslash-ends-string",
        "backslash-then-escaped-quote",
        "brackets-in-later-string",
    ],
)
def test_escapes_in_strings_do_not_change_the_counted_depth(tmp_path, payload, value, depth):
    """U6.a: escaped quotes and backslashes are string content, not structure."""
    path = tmp_path / "cache.json"
    path.write_bytes(payload)

    assert load_bounded_json(path, max_bytes=100, max_depth=depth) == value
    assert load_bounded_json(path, max_bytes=100, max_depth=depth - 1) is None


@pytest.mark.parametrize("payload", [b"]", b"[]]", b'{"a": 1}}', b"}{"])
def test_closing_bracket_before_its_opener_is_a_miss(tmp_path, payload):
    """U6.b: an unbalanced closer is a miss, not an error."""
    path = tmp_path / "cache.json"
    path.write_bytes(payload)

    assert load_bounded_json(path, max_bytes=100, max_depth=8) is None
    assert load_size_checked_json(path, max_bytes=100, max_depth=8) is None


@pytest.mark.parametrize(
    ("max_bytes", "max_depth"),
    [
        (True, 2),
        (100.0, 2),
        ("100", 2),
        (0, 2),
        (-1, 2),
        (100, True),
        (100, 2.0),
        (100, None),
        (100, -1),
    ],
    ids=[
        "bytes-bool",
        "bytes-float",
        "bytes-string",
        "bytes-zero",
        "bytes-negative",
        "depth-bool",
        "depth-float",
        "depth-none",
        "depth-negative",
    ],
)
@pytest.mark.parametrize("loader", [load_bounded_json, load_size_checked_json])
def test_invalid_bounds_are_a_programming_error(tmp_path, loader, max_bytes, max_depth):
    """U6.c: bounds are validated before any read, for both loaders."""
    path = tmp_path / "cache.json"
    path.write_bytes(b"[]")

    with pytest.raises(ValueError, match="^JSON bounds must be non-negative integers$"):
        loader(path, max_bytes=max_bytes, max_depth=max_depth)


@pytest.mark.parametrize("loader", [load_bounded_json, load_size_checked_json])
def test_smallest_valid_bounds_are_accepted(tmp_path, loader):
    """U6.c control: one byte and depth zero are valid bounds."""
    path = tmp_path / "cache.json"
    path.write_bytes(b"7")

    assert loader(path, max_bytes=1, max_depth=0) == 7
