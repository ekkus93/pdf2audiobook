"""The real-model workflow stays manual, read-only and free of uploads (W1, W5)."""

import stat
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
REAL = WORKFLOWS / "real-models.yml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(data: dict) -> set[str]:
    # PyYAML reads the bare key `on` as the boolean True.
    block = data.get("on", data.get(True))
    return set(block) if isinstance(block, dict) else set(block or [])


def test_the_workflow_is_started_by_hand_only():
    assert _triggers(_load(REAL)) == {"workflow_dispatch"}


def test_the_main_workflows_never_reference_it():
    for name in ("ci.yml", "desktop.yml"):
        assert "real-models" not in (WORKFLOWS / name).read_text(encoding="utf-8"), name


def test_permissions_are_read_only_and_the_default_token_is_the_only_credential():
    text = REAL.read_text(encoding="utf-8")
    assert _load(REAL)["permissions"] == {"contents": "read"}
    assert "secrets." not in text


def test_nothing_is_uploaded_as_an_artifact():
    assert "upload-artifact" not in REAL.read_text(encoding="utf-8")


def test_the_uv_pin_matches_the_main_ci():
    pinned = _load(REAL)["env"]["UV_VERSION"]
    assert pinned == "0.12.9"
    assert f'version: "{pinned}"' in (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")


def test_the_helper_scripts_exist_and_are_executable():
    for name in ("install-cpu-torch.sh", "stage-reference.sh"):
        path = ROOT / ".github" / "scripts" / name
        assert path.stat().st_mode & stat.S_IXUSR, name


def test_the_cpu_torch_step_uses_the_pytorch_cpu_index_and_checks_for_cuda():
    text = (ROOT / ".github" / "scripts" / "install-cpu-torch.sh").read_text(encoding="utf-8")
    assert "https://download.pytorch.org/whl/cpu" in text
    assert "torch.version.cuda is None" in text
