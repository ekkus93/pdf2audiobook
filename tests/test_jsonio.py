"""Bounded shared JSON loading for untrusted cache files."""

from pdf2audiobook.jsonio import load_bounded_json


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
