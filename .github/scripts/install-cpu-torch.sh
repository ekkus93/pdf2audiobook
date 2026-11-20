#!/usr/bin/env bash
# Replace the locked torch and torchaudio builds with CPU builds of the same versions.
# Runners have no GPU, so the CUDA wheels from uv.lock are not needed. uv.lock is not changed.
set -euo pipefail
read -r TORCH TORCHAUDIO < <(uv run --no-sync python -c "
import importlib.metadata as m
print(m.version('torch').split('+')[0], m.version('torchaudio').split('+')[0])")
uv pip install --python .venv/bin/python --reinstall-package torch --reinstall-package torchaudio \
  --extra-index-url https://download.pytorch.org/whl/cpu \
  "torch==${TORCH}+cpu" "torchaudio==${TORCHAUDIO}+cpu"
uv run --no-sync python -c "
import importlib.metadata as m
import torch
assert torch.version.cuda is None, 'a CUDA build of torch is still installed'
assert m.version('torch') == '${TORCH}+cpu', m.version('torch')
print('torch', torch.__version__, 'CPU only')"
