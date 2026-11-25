"""Tests never write the default `./audiobooks` output into the repository."""

from pathlib import Path

from pdf2audiobook.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def test_default_output_dir_resolves_inside_the_test_directory(tmp_path):
    assert Path.cwd() == tmp_path
    output = Path(Settings().general.output_dir).resolve()
    assert output == tmp_path / "audiobooks"
    assert output != ROOT / "audiobooks"
