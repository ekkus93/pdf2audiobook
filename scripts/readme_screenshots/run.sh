#!/usr/bin/env bash
# Regenerate the README walkthrough images in docs/images/readme/.
#
# Builds a small demo book in a temporary folder, runs each walkthrough step on it
# with default settings (your own config is ignored) and saves the screenshots.
#
# Needs: uv sync --extra kitten --extra dev, FFmpeg, and a Chromium for Playwright:
#   uv run --no-project --with playwright==1.65.2 playwright install chromium
# or set CHROMIUM=/path/to/chrome to use one you already have.
# Set HF_HUB_OFFLINE=1 once the Kitten model is downloaded, to keep the
# Hugging Face download warning out of the convert screenshot.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
images=$repo/docs/images/readme
port=${REVIEW_PORT:-8799}
work=$(mktemp -d)
books=$work/books
server=
cleanup() {
  if [ -n "$server" ]; then kill "$server" 2>/dev/null || true; wait "$server" 2>/dev/null || true; fi
  rm -rf "$work"
}
trap cleanup EXIT

mkdir -p "$books" "$work/config" "$images"
export XDG_CONFIG_HOME=$work/config
run() { uv run --project "$repo" "$@"; }
cap() { run python "$here/capture.py" "$images/$1" "$books" "$repo" "${@:2}"; }

run python "$here/make_demo_pdf.py" "$books/lighthouse.pdf"
cap step-1-doctor.svg -- doctor
cap step-2-analyze.svg -- analyze lighthouse.pdf --no-llm
workspace=$(cd "$books" && ls -d audiobooks/lighthouse-*)
cap step-3-convert-stops.svg -- convert lighthouse.pdf --no-llm

(cd "$books" && exec uv run --project "$repo" pdf2audiobook review \
  "$workspace/manifest.json" --port "$port" >"$work/review.log" 2>&1) &
server=$!
for _ in $(seq 1 60); do
  curl -s -o /dev/null "http://127.0.0.1:$port/" && break
  sleep 0.5
done
cap step-4-review-server.svg --log "$work/review.log" -- review "$workspace/manifest.json"
uv run --no-project --with playwright==1.65.2 \
  python "$here/shoot_review.py" "http://127.0.0.1:$port/" "$images" ${CHROMIUM:+"$CHROMIUM"}
kill "$server" && wait "$server" 2>/dev/null || true
server=

cap step-5-convert.svg -- convert lighthouse.pdf --no-llm
cap step-6-pack-m4b.svg -- pack-m4b "$workspace/manifest.json" --output lighthouse.m4b
echo "Workspace shown in the screenshots: $workspace"
echo "If it changed, update the review and pack-m4b commands in README.md to match."
