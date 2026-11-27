"""The desktop app's CI workflow runs every check spec D10.c lists (Tauri TD10.02, TD10.03)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _desktop() -> str:
    return (WORKFLOWS / "desktop.yml").read_text(encoding="utf-8")


def test_it_runs_on_master_and_pull_requests() -> None:
    workflow = _desktop()
    assert re.search(r"^  push:\s+branches: \[master\]$", workflow, re.MULTILINE)
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
        "bash e2e/isolated.sh",
    ]:
        assert command in commands, command


def test_it_shares_the_python_ci_uv_pin_and_node_major() -> None:
    python = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    desktop = _desktop()
    pin = re.compile(r'astral-sh/setup-uv@v6\s+with:\s+version: "(\d+\.\d+\.\d+)"')
    python_pin, desktop_pin = pin.search(python), pin.search(desktop)
    assert python_pin and desktop_pin and python_pin.group(1) == desktop_pin.group(1)
    assert re.search(r"actions/setup-node@v4\s+with:\s+node-version: \"22\"", desktop)


def _step(workflow: str, name: str) -> str:
    return workflow.split(f"- name: {name}", 1)[1].split("\n      - ", 1)[0]


def test_the_walkthrough_also_runs_the_shipped_appimage() -> None:
    workflow = _desktop()
    step = _step(workflow, "End-to-end walkthrough of the AppImage itself")
    assert 'APPIMAGE_EXTRACT_AND_RUN: "1"' in step
    assert "bundle/appimage/*-unsigned.AppImage" in step
    assert "bash e2e/isolated.sh" in step
    # With its built-in engine, as a user runs it (self-contained app SC7).
    assert 'E2E_BUNDLED: "1"' in step
    # The walkthrough of the build itself still drives the stand-in voice cloner.
    assert 'E2E_CLONE: "1"' in _step(workflow, "End-to-end walkthrough\n")


def test_installers_carry_the_engine_and_are_checked_on_a_clean_machine() -> None:
    workflow = _desktop()
    commands = re.findall(r"^\s+run: (.+)$", workflow, re.MULTILINE)
    build = "uv run --no-project python desktop/scripts/build_engine.py desktop/engine-dist"
    assert any(command.startswith(build) for command in commands)
    assert "python3 desktop/scripts/smoke_engine.py desktop/engine-dist/engine" in commands
    clean = "bash desktop/scripts/clean_machine_check.sh desktop/src-tauri/target/release/bundle"
    assert any(command.startswith(clean) for command in commands)
    # The engine goes in after `tauri build` and before the installers are renamed and uploaded.
    order = [
        workflow.index("npx tauri build --bundles appimage,deb"),
        workflow.index("desktop/scripts/package_engine.py desktop/engine-dist/engine"),
        workflow.index("desktop/scripts/clean_machine_check.sh"),
        workflow.index('"${file%.*}-unsigned.${file##*.}"'),
    ]
    assert order == sorted(order)
    assert "GITHUB_STEP_SUMMARY" in _step(workflow, "Add the engine to the AppImage and .deb")


def test_installers_are_uploaded_and_named_unsigned() -> None:
    workflow = _desktop()
    assert '"${file%.*}-unsigned.${file##*.}"' in workflow
    assert "bundle/appimage/*-unsigned.AppImage" in workflow
    assert "bundle/deb/*-unsigned.deb" in workflow
    assert "if-no-files-found: error" in workflow


def test_the_source_archive_is_built_and_uploaded_with_the_installers() -> None:
    # As distributed the installers are AGPL-3.0, so their source travels with them (spec C9).
    workflow = _desktop()
    step = _step(workflow, "Source archive for the installers")
    assert "desktop/scripts/source_archive.py desktop/engine-dist/engine" in step
    assert "--output desktop/src-tauri/target/release/bundle/source" in step
    upload = workflow.index("name: pdf2audiobook-desktop-linux-unsigned")
    assert workflow.index("desktop/scripts/source_archive.py") < upload
    assert "bundle/source/*-source.tar" in workflow[upload:]
