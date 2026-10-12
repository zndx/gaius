#!/usr/bin/env bash
# Side interpreter for vllm-sr/d3-flash (the checkpoint's d3_server.py).
#
# Do not install these pins into the product venv. transformers 5.17 and
# flash-linear-attention would clobber the vLLM 0.27 stack that serves
# thinking. This script only creates .devenv/d3-runtime.
#
#   scripts/d3_runtime_venv.sh
#   export GAIUS_D3_PYTHON="$PWD/.devenv/d3-runtime/bin/python"
#
# Weights are not downloaded here. The engine snapshots vllm-sr/d3-flash
# when a decisions workload starts the replicas.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${GAIUS_D3_VENV:-$ROOT/.devenv/d3-runtime}"

uv venv "$VENV" --python 3.12

# The d3 card's validated stack is torch 2.13. Product vLLM stays 0.27.
# torchvision's cu129 wheel is not on PyPI. uv resolves it as
# torchvision==0.28.0+cu129 once torch 2.13.0+cu129 is installed, and
# that pin only exists on the PyTorch index.
uv pip install --python "$VENV/bin/python" \
  --index-url https://download.pytorch.org/whl/cu129 \
  'torch==2.13.0' \
  'torchvision==0.28.0'

uv pip install --python "$VENV/bin/python" \
  'transformers==5.17.0' \
  'accelerate' \
  'safetensors' \
  'huggingface_hub' \
  'flash-linear-attention==0.5.2' \
  'einops' \
  'pillow' \
  'opencv-python-headless' \
  'fastapi' \
  'uvicorn'

echo "d3 runtime: $VENV/bin/python"
echo "export GAIUS_D3_PYTHON=$VENV/bin/python"
