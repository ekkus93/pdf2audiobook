"""The desktop app's CI workflow runs every check spec D10.c lists (Tauri TD10.02, TD10.03)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _desktop() -> str:
    return (WORKFLOWS / "desktop.yml").read_text(encoding="utf-8")


def test_it_runs_on_the_tauri_branch_and_pull_requests() -> None:
    workflow = _desktop()
    assert re.search(r"^  push:\s+branches: \[master, tauri\]$", workflow, re.MULTILINE)
    assert re.search(r"^  pull_request:$", workflow, re.MULTILINE)


def test_it_runs_the_frontend_and_rust_checks_the_build_and_the_walkthrough() -> None:
    commands = re.findall(r"^\s+run: (.+)$", _desktop(), re.MULTILINE)
    for command in [
        "npm ci",
        "npm run lint",
        "npm run typecheck",
        "npm test",
        "npm run build",
        "cargo fmt --check",
        "cargo clippy --all-targets -- -D warnings",
        "cargo test",
        "npx tauri build --bundles appimage,deb",
        'xvfb-run --auto-servernum --server-args="-screen 0 1280x800x24" npm run e2e',
    ]:
        assert command in commands, command


def test_it_shares_the_python_ci_uv_pin_and_node_major() -> None:
    python = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    desktop = _desktop()
    pin = re.compile(r'astral-sh/setup-uv@v6\s+with:\s+version: "(\d+\.\d+\.\d+)"')
    python_pin, desktop_pin = pin.search(python), pin.search(desktop)
    assert python_pin and desktop_pin and python_pin.group(1) == desktop_pin.group(1)
    assert re.search(r"actions/setup-node@v4\s+with:\s+node-version: \"22\"", desktop)


def test_the_walkthrough_also_runs_the_shipped_appimage() -> None:
    workflow = _desktop()
    step = workflow.split("- name: End-to-end walkthrough of the AppImage itself", 1)[1]
    step = step.split("\n      - ", 1)[0]
    assert 'APPIMAGE_EXTRACT_AND_RUN: "1"' in step
    assert "bundle/appimage/*-unsigned.AppImage" in step
    assert "npm run e2e" in step


def test_installers_are_uploaded_and_named_unsigned() -> None:
    workflow = _desktop()
    assert '"${file%.*}-unsigned.${file##*.}"' in workflow
    assert "bundle/appimage/*-unsigned.AppImage" in workflow
    assert "bundle/deb/*-unsigned.deb" in workflow
    assert "if-no-files-found: error" in workflow
