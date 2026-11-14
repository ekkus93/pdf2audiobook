"""Make one short MP3 sample per Kitten voice for the README.

Usage:
    uv run python scripts/voice_samples.py [--model mini] [--out docs/audio/voices]

Each voice reads the same sentence through pdf2audiobook's own Kitten provider,
so a sample sounds like a converted chapter. Needs the ``kitten`` extra and FFmpeg.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from pdf2audiobook.tts import KittenProvider

SAMPLE_TEXT = (
    "Mara Quill had kept the light at Gull Point for eleven winters. Each evening she "
    "climbed the ninety-two steps, trimmed the wick, and wound the clockwork that turned "
    "the great lens."
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default="mini", help="Kitten model alias or repository ID")
    parser.add_argument("--out", type=Path, default=Path("docs/audio/voices"))
    args = parser.parse_args()

    provider = KittenProvider(args.model)
    args.out.mkdir(parents=True, exist_ok=True)
    for voice in provider.list_voices():
        audio = provider.generate(SAMPLE_TEXT, voice=voice, speed=1.0)
        target = args.out / f"{voice}.mp3"
        # Kitten's output varies slightly from run to run, so every run rewrites each file.
        subprocess.run(
            [
                "ffmpeg", "-v", "error", "-y",
                "-f", "f32le", "-ar", str(provider.sample_rate), "-ac", "1", "-i", "-",
                "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:a", "+bitexact",
                "-codec:a", "libmp3lame", "-b:a", "64k", str(target),
            ],
            input=audio.astype("<f4").tobytes(),
            check=True,
        )  # fmt: skip
        seconds = len(audio) / provider.sample_rate
        print(f"{target}: {seconds:.1f}s")


if __name__ == "__main__":
    main()
