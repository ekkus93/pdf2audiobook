"""Native/bridge acceptance double: real CLI + FFmpeg, synthetic reference and speech only.

The model is replaced explicitly by this test launcher. Never installed as a production backend.
"""
from __future__ import annotations

import json
import sys
import time
import wave
from pathlib import Path

import numpy as np


def prepare(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    samples = (np.sin(np.arange(24000 * 6) * 2 * np.pi * 220 / 24000) * 6000).astype("<i2")
    with wave.open(str(folder / "reference.wav"), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(24000)
        stream.writeframes(samples.tobytes())
    (folder / "reference.txt").write_text("Synthetic reference transcript.")


def main() -> None:
    folder = Path(sys.argv[1])
    if sys.argv[2:] == ["--prepare"]:
        prepare(folder)
        return
    import pdf2audiobook.tts.catalog as catalog
    import pdf2audiobook.tts.clone_provider as provider
    from pdf2audiobook.cli import main as cli_main

    class FakeClone:
        sample_rate = 24000
        max_chars_per_chunk = 350
        supports_voice_listing = False

        def __init__(self, reference):
            self.reference = reference

        def generate(self, text, *, voice, speed):
            assert voice == self.reference.key
            assert "Synthetic reference transcript" not in text
            if (folder / "slow").exists():
                (folder / "inference-started").touch()
                time.sleep(30)
            with (folder / "generation.jsonl").open("a") as stream:
                stream.write(json.dumps({"characters": len(text), "voice_digest": voice}) + "\n")
            return (np.sin(np.arange(4800) * 2 * np.pi * 330 / 24000) * 0.05).astype("float32")

        def close(self):
            pass

    provider.KittenCloneProvider = FakeClone
    catalog.require_model = lambda: None
    sys.argv = ["pdf2audiobook", *sys.argv[2:]]
    cli_main()


if __name__ == "__main__":
    main()
