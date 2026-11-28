"""The real-model workflow stays manual, read-only and free of uploads (W1, W5).

The checks read the workflow text directly, so they need no YAML parser (PyYAML is not a
declared dependency).
"""

import os
import re
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

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
    for name in (
        "install-cpu-torch.sh",
        "stage-reference.sh",
        "pinned-revision.sh",
        "run-timed.sh",
        "record-cache-status.sh",
    ):
        path = ROOT / ".github" / "scripts" / name
        assert path.stat().st_mode & stat.S_IXUSR, name


def test_the_cpu_torch_step_uses_the_pytorch_cpu_index_and_checks_for_cuda():
    text = (ROOT / ".github" / "scripts" / "install-cpu-torch.sh").read_text(encoding="utf-8")
    assert "https://download.pytorch.org/whl/cpu" in text
    assert "torch.version.cuda is None" in text


def _jobs(text: str) -> dict[str, str]:
    """Each job's text, keyed by job name."""
    body = "\n".join(_top_level_block(text, "jobs"))
    parts = re.split(r"^  ([a-z][a-z-]*):\s*$", body, flags=re.M)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts), 2)}


def test_every_suite_job_runs_only_when_its_exact_name_is_selected():
    text = REAL.read_text(encoding="utf-8")
    jobs = _jobs(text)
    expected = {
        "kitten": "run_kitten",
        "asr": "run_asr",
        "clone-short": "run_clone_short",
        "clone-long": "run_clone_long",
    }
    for job, output in expected.items():
        assert f"needs.plan.outputs.{output} == 'true'" in jobs[job], job
    assert "contains(inputs.suites" not in text


def test_the_plan_step_selects_whole_suite_names_only(tmp_path):
    if shutil.which("jq") is None:
        pytest.skip("jq is not installed")
    match = re.search(
        r"\n        run: \|\n((?:          .*\n|\n)+)",
        _jobs(REAL.read_text(encoding="utf-8"))["plan"],
    )
    assert match
    script = textwrap.dedent(match.group(1))

    def plan(suites: str, models: str = "vosk") -> tuple[int, dict[str, str]]:
        output = tmp_path / "out"
        output.write_text("")
        done = subprocess.run(
            ["bash", "-c", script],
            env={
                "PATH": os.environ["PATH"],
                "SUITES": suites,
                "ASR_MODELS": models,
                "GITHUB_OUTPUT": str(output),
            },
            capture_output=True,
            text=True,
        )
        pairs = (line.split("=", 1) for line in output.read_text().splitlines())
        return done.returncode, {key: value for key, value in pairs}

    code, out = plan("clone-long")
    assert code == 0
    assert out["run_clone_long"] == "true"
    assert [out[k] for k in ("run_kitten", "run_asr", "run_clone_short")] == ["false"] * 3
    code, out = plan("kitten, asr")
    assert (out["run_kitten"], out["run_asr"], out["run_clone_short"]) == ("true", "true", "false")
    assert plan("kitten,clone")[0] != 0
    assert plan("kitten", "nope")[0] != 0


def test_the_model_caches_are_keyed_by_the_pinned_revisions():
    text = REAL.read_text(encoding="utf-8")
    assert "hashFiles('src/pdf2audiobook" not in text
    jobs = _jobs(text)
    for name in ("clone-short", "clone-long"):
        assert "pinned-revision.sh kitten2" in jobs[name], name
        assert "key: real-kitten2-${{ steps.pin.outputs.revision }}" in jobs[name], name
    assert 'pinned-revision.sh "${{ matrix.model }}"' in jobs["asr"]
    assert "key: real-asr-${{ matrix.model }}-${{ steps.pin.outputs.revision }}" in jobs["asr"]
    assert "asr/${{ matrix.model }}" in jobs["asr"]


def test_every_download_step_records_its_cache_status_in_the_summary():
    jobs = _jobs(REAL.read_text(encoding="utf-8"))
    for name in ("kitten", "asr", "clone-short", "clone-long"):
        job = jobs[name]
        assert "id: cache" in job, name
        assert "steps.cache.outputs.cache-hit" in job, name
        assert job.index("record-cache-status.sh") < job.index("pytest"), name


def test_every_test_step_records_wall_time_and_peak_memory():
    jobs = _jobs(REAL.read_text(encoding="utf-8"))
    for name in ("kitten", "asr", "clone-short", "clone-long"):
        assert "run-timed.sh" in jobs[name], name
        assert "| tee" not in jobs[name], name


def test_the_pinned_revisions_come_from_the_project_pins():
    from pdf2audiobook.tts.catalog import MODEL_REVISION
    from pdf2audiobook.verification.models import SPECS

    script = (ROOT / ".github" / "scripts" / "pinned-revision.sh").read_text(encoding="utf-8")
    assert "MODEL_REVISION" in script
    assert "SPECS[name].revision" in script
    assert re.fullmatch(r"[0-9a-f]{40}", MODEL_REVISION)
    assert all(spec.revision for spec in SPECS.values())


def test_the_timing_script_summarises_a_run_and_keeps_its_exit_status(tmp_path):
    summary = tmp_path / "summary.md"
    script = ROOT / ".github" / "scripts" / "run-timed.sh"
    env = {"PATH": os.environ["PATH"], "GITHUB_STEP_SUMMARY": str(summary)}
    done = subprocess.run(
        [str(script), "demo test", str(tmp_path / "demo.log"), "sh", "-c", "echo hello; exit 3"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 3
    assert (tmp_path / "demo.log").read_text() == "hello\n"
    row = summary.read_text().splitlines()[-1]
    assert re.fullmatch(r"\| demo test \| [0-9.]+ \| (\d+|n/a) \| 3 \|", row), row


def test_the_cache_status_script_words_each_state(tmp_path):
    summary = tmp_path / "summary.md"
    script = ROOT / ".github" / "scripts" / "record-cache-status.sh"
    env = {"PATH": os.environ["PATH"], "GITHUB_STEP_SUMMARY": str(summary)}
    for state in ("true", "false", ""):
        subprocess.run([str(script), "demo", state], env=env, check=True)
    assert summary.read_text().splitlines() == [
        "- Cache `demo`: hit (no download needed)",
        "- Cache `demo`: miss (model downloaded)",
        "- Cache `demo`: partial or unknown",
    ]
