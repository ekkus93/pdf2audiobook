#!/usr/bin/env bash
# Run the engine smoke test from inside a built AppImage on a clean machine (self-contained SC7):
# a stock Ubuntu 22.04 container with no Python, uv, FFmpeg or Tesseract, and no network.
#
#   desktop/scripts/clean_machine_check.sh path/to/pdf2audiobook.AppImage
#
# The AppImage unpacks itself (no FUSE needed) and the smoke test runs with the engine's own
# Python, so nothing from this checkout or the host is used but the two files mounted read-only.
set -euo pipefail

image=$(readlink -f "$1")
scripts=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# Pinned by digest (2026-11-27): the same clean machine every run.
base="ubuntu:22.04@sha256:b000e69a50ff940390233025e7a337fb8469b509e2334fa4d018ac30f3e18cdb"

docker run --rm --network none \
  -v "$image:/check/app.AppImage:ro" \
  -v "$scripts/smoke_engine.py:/check/smoke_engine.py:ro" \
  "$base" bash -euo pipefail -c '
    for tool in python3 uv ffmpeg tesseract; do
      if command -v "$tool" >/dev/null; then echo "not a clean machine: $tool is installed" >&2; exit 1; fi
    done
    cd /tmp
    /check/app.AppImage --appimage-extract >/dev/null
    engine=/tmp/squashfs-root/usr/lib/pdf2audiobook/engine
    "$engine/bin/python3" -I /check/smoke_engine.py "$engine" --offline
  '
