# Tinybox 6x4090 + devenv + vLLM Setup Guide

**Date:** 2025-12-02
**Hardware:** Tinybox 6x RTX 4090 (24GB each = 144GB total VRAM)

## Problem

vLLM couldn't detect GPUs because Nix/devenv's LD_LIBRARY_PATH was hiding the system NVIDIA drivers installed on the tinybox.

## Solution Applied

**Updated `devenv.nix` to include system NVIDIA driver paths:**

```nix
# Library paths for Python C extensions and CUDA
# Include system NVIDIA drivers (tinybox custom installation)
env.LD_LIBRARY_PATH = lib.concatStringsSep ":" [
  (lib.makeLibraryPath [
    pkgs.zlib
    pkgs.stdenv.cc.cc.lib  # libstdc++
  ])
  # System NVIDIA drivers (for tinybox 6x4090)
  "/usr/lib/x86_64-linux-gnu"
  # CUDA toolkit paths (if needed)
  "/usr/local/cuda/lib64"
  "/usr/local/cuda/extras/CUPTI/lib64"
];
```

## GPU Allocation Strategy

**Hardware:** 6x RTX 4090 @ 24GB VRAM each

**Endpoint Configuration** (`config/base.conf`):

| Endpoint | GPUs | VRAM | Model | Purpose |
|----------|------|------|-------|---------|
| reasoning | 0-1 | 48GB | Qwen/QwQ-32B (TP=2) | Deep reasoning, math, logic |
| coding | 2 | 24GB | Qwen/Qwen3-Coder-30B | Code generation, structured output |
| fast | 3 | 24GB | Mistral-7B | Quick responses, simple tasks |
| orchestration | 4 | 24GB | nvidia/Orchestrator-8B | Main event loop, command routing |
| standby | 5 | 24GB | (dynamic) | Hot standby, overflow capacity |

**Total capacity:** 5 concurrent models using 144GB VRAM

## Steps to Complete Setup

### 1. Exit and Re-enter devenv Shell

The LD_LIBRARY_PATH changes require a fresh shell:

```bash
# Exit current shell
exit

# Re-enter devenv
cd /home/rch/local/src/zndx/gaius
devenv shell
```

### 2. Verify CUDA Detection

```bash
# Should now show 6 GPUs
uv run python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU count: {torch.cuda.device_count()}')"

# Expected output:
# CUDA available: True
# GPU count: 6
```

### 3. Test vLLM Import

```bash
# Should work now
uv run python -c "import vllm; print('✓ vLLM imported successfully')"
```

### 4. Start Default Model (nvidia/Orchestrator-8B)

```bash
# Via CLI
uv run python -m gaius.cli --cmd "/inference ensure" --format json

# Or via TUI
uv run gaius
# Then run: /inference ensure
```

Expected progress:
```
[0%] Checking orchestrator status
[20%] Starting orchestrator endpoint
[40%] Waiting for model to load
[90%] Loading model into VRAM (GPU 4)
[100%] Ready
```

### 5. Check All Endpoints

```bash
uv run python -m gaius.cli --cmd "/inference status" --format json
```

Should show:
```json
{
  "orchestrator_running": true,
  "default_model_ready": true,
  "endpoints": {
    "orchestration": "healthy"
  }
}
```

### 6. Start Additional Models (Optional)

```bash
# Start reasoning endpoint (QwQ-32B on GPUs 0-1)
uv run python -m gaius.cli --cmd "/inference start reasoning" --format json

# Start coding endpoint (Qwen Coder 30B on GPU 2)
uv run python -m gaius.cli --cmd "/inference start coding" --format json

# Start fast endpoint (Mistral-7B on GPU 3)
uv run python -m gaius.cli --cmd "/inference start fast" --format json
```

## Testing the Full Stack

### Test Script: `serve.sh`

Your serve.sh should now work:

```bash
export LOCAL_MODEL="nvidia/Orchestrator-8B"
export OPENAI_API_PORT="8084"
./serve.sh
```

Expected: vLLM server starts on GPU 4, listening on port 8084.

### Test via Gaius CLI

```bash
# Submit a simple query to test orchestrator
uv run python -m gaius.cli --cmd "/ask what is 2+2" --format json
```

### Test TUI Startup

```bash
uv run gaius
# Should show background task: "Starting nvidia/Orchestrator-8B"
# Press 'g' to see ThinkPanel with progress
```

## Model Download Requirements

Models will auto-download from HuggingFace on first use:

```bash
# Pre-download to avoid startup delays (optional)
huggingface-cli download nvidia/Orchestrator-8B
huggingface-cli download Qwen/QwQ-32B
huggingface-cli download Qwen/Qwen3-Coder-30B-A3B-Instruct
huggingface-cli download mistralai/Mistral-7B-Instruct-v0.3
```

**Storage requirement:** ~100GB total for all models

## VRAM Utilization

With all 5 endpoints running:

- GPU 0-1: 32B model (TP=2) → ~44GB used
- GPU 2: 30B model → ~22GB used
- GPU 3: 7B model → ~8GB used
- GPU 4: 8B model → ~10GB used
- GPU 5: Idle (standby)

**Total VRAM used:** ~84GB / 144GB (58% utilization)
**Headroom:** 60GB for dynamic batching and KV cache

## Troubleshooting

### If PyTorch still can't see CUDA:

```bash
# Check LD_LIBRARY_PATH includes NVIDIA drivers
echo $LD_LIBRARY_PATH | tr ':' '\n' | grep nvidia

# Should include: /usr/lib/x86_64-linux-gnu
```

### If vLLM fails with "device type" error:

```bash
# Check CUDA libraries are accessible
ldd $(uv run python -c "import torch; print(torch.__file__.replace('__init__.py', 'lib/libtorch_cuda.so'))")

# Should resolve all symbols (no "not found" errors)
```

### If models fail to start:

```bash
# Check GPU status
nvidia-smi

# Check orchestrator logs
uv run python -m gaius.cli --cmd "/gpu logs orchestration" --format json

# Check for OOM or other errors
```

## Performance Tuning

### For Large Batch Workloads

Increase KV cache in `config/base.conf`:

```hocon
gaius.inference.orchestrator.vllm {
  gpu_memory_utilization = 0.95  # From 0.9 (default)
  max_model_len = 32768
}
```

### For Low-Latency Responses

Reduce batch wait time (future config option):
```hocon
gaius.inference.orchestrator.vllm {
  max_num_batched_tokens = 2048  # Smaller batches
  max_num_seqs = 128  # Fewer concurrent requests
}
```

## Files Changed

1. `devenv.nix:12-22` - Added NVIDIA driver paths to LD_LIBRARY_PATH
2. `devenv.nix:26-27` - Removed ansible (Python 3.13 conflict)
3. `config/base.conf:127-168` - GPU endpoint configuration (already optimal)

## Status

✅ devenv.nix updated with tinybox NVIDIA paths
✅ GPU allocation strategy defined
⏳ User needs to restart shell
⏳ Verify CUDA detection
⏳ Start models and test

## Next Steps

1. **Restart shell:** `exit && devenv shell`
2. **Verify CUDA:** `uv run python -c "import torch; print(torch.cuda.device_count())"`
3. **Start orchestrator:** `uv run python -m gaius.cli --cmd "/inference ensure"`
4. **Test query:** `/ask what is the meaning of life`
5. **Monitor:** `nvidia-smi -l 1` (watch GPU utilization)
