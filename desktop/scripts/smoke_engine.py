"""Smoke-test a built engine the way a clean machine would run it (self-contained app SC1, SC4).

    python3 desktop/scripts/smoke_engine.py ENGINE_DIR [--allow-system-ffmpeg] [--offline]

Runs ENGINE_DIR/bin/pdf2audiobook with an empty environment, no network when `unshare -rn`
is available, and a minimal PATH. It checks `doctor --json`, converts a synthetic two-chapter
text PDF to MP3s, and converts a synthetic image-only page through OCR. The fixtures are made
by the engine's own PyMuPDF and contain no book content.

--allow-system-ffmpeg lets a development build made with --without-ffmpeg use /usr/bin/ffmpeg.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FIXTURES = """
import sys
import pymupdf

folder = sys.argv[1]
text = pymupdf.open()
for n in (1, 2):
    page = text.new_page()
    page.insert_text((72, 90), f"Chapter {n}", fontsize=20)
    page.insert_text((72, 140), f"This is the narration for chapter {n}. It is short.", fontsize=12)
text.save(f"{folder}/text.pdf")

source = pymupdf.open()
page = source.new_page()
page.insert_text((72, 100), "Chapter 1", fontsize=22)
page.insert_text((72, 160), "The lighthouse keeper climbed the stairs at dusk.", fontsize=14)
pixmap = page.get_pixmap(dpi=200)
scanned = pymupdf.open()
image = scanned.new_page(width=page.rect.width, height=page.rect.height)
image.insert_image(image.rect, pixmap=pixmap)
scanned.save(f"{folder}/scanned.pdf")
"""

# Every other way the engine uses FFmpeg, so a smaller FFmpeg build cannot drop one unnoticed:
# reference recordings (WAV, FLAC), speed changes (atempo) and decoding for the recognizers.
FFMPEG_USES = """
import sys
from pathlib import Path

import numpy as np
import soundfile

from pdf2audiobook.bundle import configure_environment

configure_environment()
from pdf2audiobook.tts.clone_provider import change_speed
from pdf2audiobook.tts.cloning import decode_reference
from pdf2audiobook.verification.backends import decode

folder, mp3 = Path(sys.argv[1]), Path(sys.argv[2])
tone = (0.2 * np.sin(2 * np.pi * 220 * np.arange(24000 * 6) / 24000)).astype("float32")
for kind in ("WAV", "FLAC"):
    reference = folder / f"reference.{kind.lower()}"
    soundfile.write(reference, tone, 24000, format=kind)
    decode_reference(reference.read_bytes(), reference.suffix)
    print(f"ok: decoded a {kind} reference recording")
faster = change_speed(tone, 1.5)
assert 0.6 < faster.size / tone.size < 0.7, faster.size
print("ok: changed speech speed")
decode(mp3, folder / "16k.wav")
assert soundfile.info(folder / "16k.wav").samplerate == 16000
print("ok: decoded an MP3 for the speech recognizers")
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("engine", type=Path)
    parser.add_argument("--allow-system-ffmpeg", action="store_true")
    parser.add_argument(
        "--offline", action="store_true", help="The network is already off (a container)."
    )
    args = parser.parse_args()
    engine = args.engine.resolve()
    launcher = engine / "bin" / "pdf2audiobook"
    path = "/usr/bin:/bin" if args.allow_system_ffmpeg else "/bin"
    isolate = (
        ["unshare", "-rn"]
        if not args.offline and shutil.which("unshare") and _works(["unshare", "-rn", "true"])
        else []
    )
    if not isolate and not args.offline:
        print("note: unshare is unavailable; running with the network enabled", file=sys.stderr)

    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp)
        home = work / "home"
        home.mkdir()
        environ = {"HOME": str(home), "PATH": path, "TMPDIR": temp, "LANG": "C.UTF-8"}

        def cli(*arguments: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [*isolate, "env", "-i", *(f"{k}={v}" for k, v in environ.items()), str(launcher), *arguments],
                capture_output=True, text=True, check=False, timeout=900,
            )  # fmt: skip

        subprocess.run([str(engine / "bin" / "python3"), "-c", FIXTURES, temp], check=True)
        doctor = cli("doctor", "--no-config", "--json")
        _check(doctor.returncode == 0, "doctor ran", doctor)
        report = json.loads(doctor.stdout)
        for key in ("ffmpeg", "tesseract", "kitten_installed"):
            _check(report[key] is True, f"doctor reports {key}", doctor)
        _check(report["ocr_missing_languages"] == [], "English OCR data is present", doctor)

        for name, ocr in (("text", "never"), ("scanned", "always")):
            out = work / f"out-{name}"
            run = cli("convert", f"{temp}/{name}.pdf", "--no-config", "--no-llm", "--ocr", ocr,
                      "--output", str(out), "--json")  # fmt: skip
            _check(run.returncode == 0, f"converted the {name} PDF", run)
            mp3s = sorted(out.glob("*/audio/*.mp3"))
            _check(
                len(mp3s) >= 1 and all(m.stat().st_size > 1000 for m in mp3s),
                f"{name} PDF gave MP3s",
                run,
            )
            print(f"ok: {name} PDF -> {len(mp3s)} MP3(s)")
            if name == "text":
                book, chapter = mp3s[0].parent.parent, mp3s[0]
        m4b = work / "book.m4b"
        packed = cli("pack-m4b", str(book / "manifest.json"), "--output", str(m4b), "--no-config",
                     "--json")  # fmt: skip
        _check(packed.returncode == 0 and m4b.stat().st_size > 1000, "packed an M4B", packed)
        print("ok: text PDF -> M4B audiobook")
        uses = subprocess.run(
            [*isolate, "env", "-i", *(f"{k}={v}" for k, v in environ.items()),
             str(engine / "bin" / "python3"), "-I", "-c", FFMPEG_USES, temp, str(chapter)],
            capture_output=True, text=True, check=False, timeout=300,
        )  # fmt: skip
        _check(uses.returncode == 0, "every FFmpeg use works", uses)
        print(uses.stdout, end="")
    print("ok: engine smoke test passed")


def _works(command: list[str]) -> bool:
    return subprocess.run(command, capture_output=True, check=False).returncode == 0


def _check(condition: bool, what: str, run: subprocess.CompletedProcess[str]) -> None:
    if not condition:
        sys.exit(
            f"FAILED: {what}\n--- stderr (last lines) ---\n"
            + "\n".join(run.stderr.splitlines()[-15:])
        )


if __name__ == "__main__":
    main()
