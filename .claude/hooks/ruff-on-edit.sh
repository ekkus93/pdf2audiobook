#!/usr/bin/env bash
# PostToolUse(Write|Edit): fix import order and ruff-format edited .py files
# (CI enforces `ruff format --check .` repository-wide).
f=$(jq -r '.tool_input.file_path // .tool_response.filePath // empty')
case "$f" in *.py) ;; *) exit 0 ;; esac
root="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
cd "$root" || exit 0
rel="${f#"$root"/}"
[ -f "$rel" ] || exit 0
uv run --frozen --extra dev ruff check --select I --fix --quiet "$rel"
uv run --frozen --extra dev ruff format --quiet "$rel"
