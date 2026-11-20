"""The real-model workflow stays manual, read-only and free of uploads (W1, W5).

The checks read the workflow text directly, so they need no YAML parser (PyYAML is not a
declared dependency).
"""

import re
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
REAL = WORKFLOWS / "real-models.yml"


def _top_level_block(text: str, key: str) -> list[str]:
    """Lines indented under a top-level key such as `on:` or `permissions:`."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.rstrip() == f"{key}:")
    block = []
    for line in lines[start + 1 :]:
        if line and not line.startswith(" ") and not line.startswith("#"):
            break
        block.append(line)
    return block


def test_the_workflow_is_started_by_hand_only():
    block = _top_level_block(REAL.read_text(encoding="utf-8"), "on")
    triggers = [line.strip() for line in block if re.match(r"^  [a-z_]+:\s*$", line)]
    assert triggers == ["workflow_dispatch:"]


def test_the_main_workflows_never_reference_it():
    for name in ("ci.yml", "desktop.yml"):
        assert "real-models" not in (WORKFLOWS / name).read_text(encoding="utf-8"), name


def test_permissions_are_read_only_and_the_default_token_is_the_only_credential():
    text = REAL.read_text(encoding="utf-8")
    assert [line.strip() for line in _top_level_block(text, "permissions")] == ["contents: read"]
    assert "secrets." not in text


def test_nothing_is_uploaded_as_an_artifact():
    assert "upload-artifact" not in REAL.read_text(encoding="utf-8")


def test_the_uv_pin_matches_the_main_ci():
    text = REAL.read_text(encoding="utf-8")
    assert 'UV_VERSION: "0.12.9"' in text
    assert 'version: "0.12.9"' in (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")


def test_the_helper_scripts_exist_and_are_executable():
    for name in ("install-cpu-torch.sh", "stage-reference.sh"):
        path = ROOT / ".github" / "scripts" / name
        assert path.stat().st_mode & stat.S_IXUSR, name


def test_the_cpu_torch_step_uses_the_pytorch_cpu_index_and_checks_for_cuda():
    text = (ROOT / ".github" / "scripts" / "install-cpu-torch.sh").read_text(encoding="utf-8")
    assert "https://download.pytorch.org/whl/cpu" in text
    assert "torch.version.cuda is None" in text
