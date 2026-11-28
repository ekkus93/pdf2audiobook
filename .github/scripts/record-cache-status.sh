#!/usr/bin/env bash
# Append one cache line to the job summary. Usage: record-cache-status.sh <name> <cache-hit>
# <cache-hit> is the `cache-hit` output of actions/cache: "true" (exact hit), "false" (the
# cache was missing, so the model is downloaded) or empty (a restore-key hit or no result).
set -euo pipefail
case "${2:-}" in
  true) state="hit (no download needed)" ;;
  false) state="miss (model downloaded)" ;;
  *) state="partial or unknown" ;;
esac
echo "- Cache \`$1\`: $state" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
