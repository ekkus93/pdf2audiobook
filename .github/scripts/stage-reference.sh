#!/usr/bin/env bash
# Write the public Kitten 2 reference transcript to a runner temporary folder, and export the
# reference and transcript paths for the clone tests. The transcript text is never printed.
set -euo pipefail
DEST="$RUNNER_TEMP/reference"
mkdir -p "$DEST"
uv run --no-sync python - "$DEST" <<'PY'
import json
import os
import sys
from pathlib import Path

from pdf2audiobook.tts.catalog import model_directory

dest = Path(sys.argv[1])
voices = model_directory() / "model" / "voices"
voice = json.loads((voices / "voices.json").read_text(encoding="utf-8"))["Bruno"]
transcript = dest / "reference.txt"
transcript.write_text(voice["transcript"], encoding="utf-8")
with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as env:
    env.write(f"PDF2AUDIOBOOK_TEST_CLONE_REFERENCE={voices / voice['reference']}\n")
    env.write(f"PDF2AUDIOBOOK_TEST_CLONE_TRANSCRIPT={transcript}\n")
PY
