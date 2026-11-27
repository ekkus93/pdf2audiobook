"""Smoke-test a built engine the way a clean machine would run it (self-contained app SC1, SC4).

    python3 desktop/scripts/smoke_engine.py ENGINE_DIR [--allow-system-ffmpeg]

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


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("engine", type=Path)
    parser.add_argument("--allow-system-ffmpeg", action="store_true")
    args = parser.parse_args()
    engine = args.engine.resolve()
    launcher = engine / "bin" / "pdf2audiobook"
    path = "/usr/bin:/bin" if args.allow_system_ffmpeg else "/bin"
    isolate = (
        ["unshare", "-rn"] if shutil.which("unshare") and _works(["unshare", "-rn", "true"]) else []
    )
    if not isolate:
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
