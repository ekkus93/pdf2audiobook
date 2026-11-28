#!/usr/bin/env bash
# Run a command, tee its output to a log, and append its wall time and peak RSS to the job
# summary. Usage: run-timed.sh <label> <log-file> <command> [args...]
# The label is a test id, never a path. The command's exit status is returned unchanged.
set -uo pipefail
label=$1
log=$2
shift 2
timing=$(mktemp)
if [ -x /usr/bin/time ]; then
  /usr/bin/time -f '%e %M' -o "$timing" "$@" 2>&1 | tee "$log"
  status=${PIPESTATUS[0]}
  read -r wall rss_kib < <(tail -n 1 "$timing") || true
  rss_mib=$(awk -v k="${rss_kib:-0}" 'BEGIN {printf "%.0f", k / 1024}')
else
  start=$(date +%s)
  "$@" 2>&1 | tee "$log"
  status=${PIPESTATUS[0]}
  wall=$(($(date +%s) - start))
  rss_mib="n/a"
fi
rm -f "$timing"
{
  echo "### Timing: ${label}"
  echo "| Test | Wall time (s) | Peak RSS (MiB) | Exit status |"
  echo "|---|---|---|---|"
  echo "| ${label} | ${wall:-n/a} | ${rss_mib} | ${status} |"
} >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
exit "$status"
