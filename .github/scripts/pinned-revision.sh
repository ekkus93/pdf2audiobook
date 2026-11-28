#!/usr/bin/env bash
# Print the pinned revision of a model, read from the project's own pins, for use as a cache key.
# Usage: pinned-revision.sh kitten2|whisper|wav2vec2|vosk
# With GITHUB_OUTPUT set, also writes `revision=<value>` there. Needs the project installed.
set -euo pipefail
revision=$(uv run --no-sync python - "$1" <<'PY'
import sys

name = sys.argv[1]
if name == "kitten2":
    from pdf2audiobook.tts.catalog import MODEL_REVISION

    print(MODEL_REVISION)
else:
    from pdf2audiobook.verification.models import SPECS

    print(SPECS[name].revision)  # type: ignore[index]
PY
)
echo "$revision"
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  echo "revision=$revision" >> "$GITHUB_OUTPUT"
fi
