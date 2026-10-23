"""Third-party backends must not print book text or adverts onto CLI stdout."""

import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pymupdf

from pdf2audiobook.tts import KittenProvider

SENTINEL = "PRIVATE_SYNTHETIC_BOOK_TEXT_202"


def test_kitten_backend_prints_are_discarded(monkeypatch, capsys):
    module = ModuleType("kittenml")

    class ChattyKitten:
        # Mirrors kittenml, which prints each chunk before synthesis.
        available_voices = ["Jasper"]

        def __init__(self, model_id):
            print(f"Loading {model_id}")

        def generate(self, text, *, voice, speed):
            print(f"Generating audio for text: {text}")
            return np.full(240, 0.1, dtype=np.float32)

    module.KittenTTS = ChattyKitten
    monkeypatch.setitem(sys.modules, "kittenml", module)
    provider = KittenProvider("mini")
    audio = provider.generate(f"{SENTINEL}.", voice="Jasper", speed=1.0)
    assert audio.size == 240
    out = capsys.readouterr().out
    assert SENTINEL not in out
    assert out == ""


def _book(path: Path) -> None:
    document = pymupdf.open()
    for number in (1, 2):
        page = document.new_page()
        page.insert_text((72, 100), f"Chapter {number}", fontsize=18)
        page.insert_text((72, 140), f"Synthetic chapter {number} prose.", fontsize=11)
    document.set_toc([[1, "Chapter 1", 1], [1, "Chapter 2", 2]])
    document.save(path)


def test_analyze_json_stdout_is_pure_json(tmp_path):
    source = tmp_path / "book.pdf"
    _book(source)
    result = subprocess.run(
        [
            sys.executable, "-c", "from pdf2audiobook.cli import app; app()",
            "analyze", str(source), "--no-config", "--no-llm", "--output", str(tmp_path / "out"), "--json",
        ],
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert Path(report["manifest"]).is_file()
